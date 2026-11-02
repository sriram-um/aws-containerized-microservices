"""Exercise 12: end-to-end test of the Orders Service through the public ALB.

Creates two Cognito test users (alice, bob) on first run, with random passwords stored OUTSIDE
the repo in ~/.containerized-microservices-test-users.json, signs them in (USER_PASSWORD_AUTH,
ID tokens) and checks: 401 without/with a bad token, 201 create, 200 own read, 404 for another
user's order, 400 validation, plus latency of POST/GET.

  .venv/Scripts/python scripts/orders_e2e.py [--requests 50]
Uses the AWS "default" profile (account 977534234172) - never the ambient AWS_PROFILE.
"""
import argparse
import json
import secrets
import statistics
import string
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3

EXPECTED_ARN = "arn:aws:iam::977534234172:user/sriram"
STACK = "containerized-microservices"
CREDS = Path.home() / ".containerized-microservices-test-users.json"
USERS = ["alice+orders@example.com", "bob+orders@example.com"]
sys.stdout.reconfigure(encoding="utf-8")


def password() -> str:
    # Satisfies the pool policy: >= 12 chars, upper, lower, digit, symbol
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(20)) + "Aa1!"


def ensure_users(idp, pool_id: str) -> dict:
    creds = json.loads(CREDS.read_text()) if CREDS.exists() else {}
    for email in USERS:
        if email in creds:
            continue
        pw = password()
        try:
            idp.admin_create_user(UserPoolId=pool_id, Username=email, MessageAction="SUPPRESS",
                                  UserAttributes=[{"Name": "email", "Value": email},
                                                  {"Name": "email_verified", "Value": "true"}])
        except idp.exceptions.UsernameExistsException:
            pass
        idp.admin_set_user_password(UserPoolId=pool_id, Username=email, Password=pw, Permanent=True)
        creds[email] = pw
    CREDS.write_text(json.dumps(creds, indent=1))
    CREDS.chmod(0o600)
    return creds


def id_token(idp, client_id: str, email: str, pw: str) -> str:
    r = idp.initiate_auth(ClientId=client_id, AuthFlow="USER_PASSWORD_AUTH",
                          AuthParameters={"USERNAME": email, "PASSWORD": pw})
    return r["AuthenticationResult"]["IdToken"]


def call(method: str, url: str, token: str | None = None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            status, payload = r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        status, payload = e.code, json.loads(e.read() or b"{}")
    return status, payload, (time.perf_counter() - t) * 1000


def check(name: str, ok: bool, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", type=int, default=50)
    args = ap.parse_args()
    session = boto3.Session(profile_name="default", region_name="us-east-1")
    if (arn := session.client("sts").get_caller_identity()["Arn"]) != EXPECTED_ARN:
        sys.exit(f"wrong AWS identity {arn}")
    out = {o["OutputKey"]: o["OutputValue"] for o in
           session.client("cloudformation").describe_stacks(StackName=STACK)["Stacks"][0]["Outputs"]}
    idp = session.client("cognito-idp")
    creds = ensure_users(idp, out["UserPoolId"])
    alice = id_token(idp, out["UserPoolClientId"], USERS[0], creds[USERS[0]])
    bob = id_token(idp, out["UserPoolClientId"], USERS[1], creds[USERS[1]])
    base = out["OrdersUrl"]
    order = {"items": [{"itemId": "SKU-1001", "productName": "Wireless Mouse", "quantity": 2, "unitPrice": 24.99},
                       {"itemId": "SKU-1003", "productName": "USB-C Hub", "quantity": 1, "unitPrice": 39.5}]}

    print(f"Orders API {base}")
    results = []
    s, p, _ = call("POST", base, None, order)
    results.append(check("POST without token -> 401", s == 401, s))
    s, p, _ = call("POST", base, alice[:-5] + "xxxxx", order)
    results.append(check("POST with tampered token -> 401", s == 401, s))
    s, p, ms = call("POST", base, alice, order)
    results.append(check("POST as alice -> 201", s == 201 and p.get("total") == "89.48", f"{s} {p} {ms:.0f} ms"))
    order_id = p.get("orderId", "missing")
    s, p, ms = call("GET", f"{base}/{order_id}", alice)
    results.append(check("GET own order -> 200 with 2 lines", s == 200 and p.get("itemCount") == 2, f"{s} {ms:.0f} ms"))
    s, p, _ = call("GET", f"{base}/{order_id}", bob)
    results.append(check("GET alice's order as bob -> 404", s == 404, s))
    s, p, _ = call("POST", base, alice, {"items": [{"itemId": "a", "quantity": 0, "unitPrice": 1}]})
    results.append(check("POST invalid quantity -> 400", s == 400, p.get("message")))
    s, p, _ = call("GET", base.replace("/orders", "/products"))
    results.append(check("product API unaffected (/products) -> 200", s == 200, s))

    post_ms, get_ms = [], []
    for _ in range(args.requests):
        s, p, ms = call("POST", base, alice, order)
        post_ms.append(ms)
        s2, _, ms2 = call("GET", f"{base}/{p.get('orderId')}", alice)
        get_ms.append(ms2)
        results.append(s == 201 and s2 == 200)
    q = lambda v, n: statistics.quantiles(v, n=100)[n - 1]
    print(f"  latency over {args.requests} POST+GET pairs (laptop -> ALB -> Fargate -> DynamoDB): "
          f"POST p50 {q(post_ms, 50):.0f} ms / p95 {q(post_ms, 95):.0f} ms, "
          f"GET p50 {q(get_ms, 50):.0f} ms / p95 {q(get_ms, 95):.0f} ms")
    print(f"{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
