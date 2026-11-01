from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from product_service.main import app, get_repository
from product_service.repository import _to_json


class FakeRepository:
    def __init__(self, products=None, error=None):
        self._products = products or []
        self._error = error

    def list_products(self):
        if self._error:
            raise self._error
        return self._products


@pytest.fixture
def client():
    # No `with TestClient(...)`: the lifespan (which opens the DB pool) is not run in unit tests
    yield TestClient(app)
    app.dependency_overrides.clear()


def use_repo(repo):
    app.dependency_overrides[get_repository] = lambda: repo


def test_health_does_not_need_database(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_products(client):
    products = [{"id": 1, "sku": "SKU-1", "name": "Mouse", "description": "", "price": 9.99, "stock": 3}]
    use_repo(FakeRepository(products))
    resp = client.get("/products")
    assert resp.status_code == 200
    assert resp.json() == {"products": products, "count": 1}


def test_list_products_empty(client):
    use_repo(FakeRepository([]))
    assert client.get("/products").json() == {"products": [], "count": 0}


@pytest.mark.parametrize("error", [PoolTimeout("timeout"), psycopg.OperationalError("down")])
def test_database_unavailable_returns_503(client, error):
    use_repo(FakeRepository(error=error))
    resp = client.get("/products")
    assert resp.status_code == 503
    assert resp.json() == {"message": "Database unavailable"}


def test_unknown_route_is_404(client):
    assert client.get("/nope").status_code == 404


def test_decimal_price_serialised_as_number():
    assert _to_json({"price": Decimal("24.99"), "name": "x"}) == {"price": 24.99, "name": "x"}
