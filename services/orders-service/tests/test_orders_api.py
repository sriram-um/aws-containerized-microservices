"""Orders API tests: DynamoDB is moto, the Cognito JWKS is replaced by a local RSA key pair."""
import json
import os
import time

import boto3
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from moto import mock_aws

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

from orders_service import main  # noqa: E402
from orders_service.auth import TokenVerifier  # noqa: E402
from orders_service.orders import OrderRepository  # noqa: E402

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
S = main.settings


class FakeSigningKey:
    key = KEY.public_key()


class LocalVerifier(TokenVerifier):
    """Real claim checks; only the JWKS download is replaced."""
    def __init__(self, settings):
        super().__init__(settings)
        self._jwks.get_signing_key_from_jwt = lambda token: FakeSigningKey()


def token(sub="user-1", **overrides):
    claims = {"sub": sub, "aud": S.app_client_id, "iss": S.issuer, "token_use": "id",
              "iat": int(time.time()), "exp": int(time.time()) + 300, **overrides}
    return jwt.encode(claims, KEY, algorithm="RS256")


def auth(sub="user-1", **overrides):
    return {"Authorization": f"Bearer {token(sub, **overrides)}"}


@pytest.fixture
def client():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName=S.table_name, BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "orderId", "KeyType": "HASH"},
                       {"AttributeName": "itemId", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "orderId", "AttributeType": "S"},
                                  {"AttributeName": "itemId", "AttributeType": "S"}])
        main.app.dependency_overrides[main.get_repository] = lambda: OrderRepository(table)
        main.app.dependency_overrides[main.get_verifier] = lambda: LocalVerifier(S)
        yield TestClient(main.app)
        main.app.dependency_overrides.clear()


ORDER = {"items": [{"itemId": "SKU-1001", "productName": "Wireless Mouse", "quantity": 2, "unitPrice": 24.99},
                   {"itemId": "SKU-1003", "quantity": 1, "unitPrice": "39.50"}]}


def test_health_needs_no_token(client):
    assert client.get("/health").status_code == 200


def test_create_and_read_own_order(client):
    resp = client.post("/orders", json=ORDER, headers=auth())
    assert resp.status_code == 201
    body = resp.json()
    assert body["itemCount"] == 2 and body["total"] == "89.48"
    got = client.get(f"/orders/{body['orderId']}", headers=auth())
    assert got.status_code == 200
    assert {i["itemId"] for i in got.json()["items"]} == {"SKU-1001", "SKU-1003"}
    assert got.json()["items"][0]["status"] == "CREATED"


def test_other_customer_gets_404(client):
    order_id = client.post("/orders", json=ORDER, headers=auth("alice")).json()["orderId"]
    assert client.get(f"/orders/{order_id}", headers=auth("bob")).status_code == 404


def test_unknown_order_404(client):
    assert client.get("/orders/does-not-exist", headers=auth()).status_code == 404


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer not-a-jwt"}])
def test_missing_or_malformed_token_401(client, headers):
    assert client.post("/orders", json=ORDER, headers=headers).status_code == 401


@pytest.mark.parametrize("bad", [{"exp": int(time.time()) - 10}, {"aud": "other-client"},
                                 {"iss": "https://example.com"}, {"token_use": "access"}])
def test_invalid_claims_401(client, bad):
    assert client.post("/orders", json=ORDER, headers=auth(**bad)).status_code == 401


def test_customer_id_comes_from_token_not_body(client):
    body = {**ORDER, "customerId": "attacker"}
    order_id = client.post("/orders", json=body, headers=auth("real-user")).json()["orderId"]
    assert client.get(f"/orders/{order_id}", headers=auth("attacker")).status_code == 404
    assert client.get(f"/orders/{order_id}", headers=auth("real-user")).status_code == 200


@pytest.mark.parametrize("payload, message", [
    ({}, "'items' must be a non-empty list"),
    ({"items": []}, "'items' must be a non-empty list"),
    ({"items": [{"itemId": "a", "quantity": 0, "unitPrice": 1}]}, "items[0].quantity must be a positive integer"),
    ({"items": [{"itemId": "a", "quantity": True, "unitPrice": 1}]}, "items[0].quantity must be a positive integer"),
    ({"items": [{"itemId": "a", "quantity": 1, "unitPrice": -1}]}, "items[0].unitPrice must be a non-negative number"),
    ({"items": [{"itemId": "a", "quantity": 1, "unitPrice": "x"}]}, "items[0].unitPrice must be a number"),
    ({"items": [{"itemId": "a", "quantity": 1, "unitPrice": 1}, {"itemId": "a", "quantity": 1, "unitPrice": 1}]}, "duplicate itemId 'a'"),
    ({"items": [{"itemId": f"i{n}", "quantity": 1, "unitPrice": 1} for n in range(26)]}, "an order can contain at most 25 items"),
    ([1, 2], "request body must be a JSON object"),
])
def test_validation_400(client, payload, message):
    resp = client.post("/orders", content=json.dumps(payload), headers={**auth(), "Content-Type": "application/json"})
    assert resp.status_code == 400 and resp.json()["message"] == message


def test_invalid_json_400(client):
    resp = client.post("/orders", content="{not json", headers={**auth(), "Content-Type": "application/json"})
    assert resp.status_code == 400
