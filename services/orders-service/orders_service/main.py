"""Orders Service: Project 3's orders API on ECS (port 3000, behind the shared ALB under /orders).

POST /orders            -> 201 {orderId, itemCount, total}; customerId = verified token `sub`
GET  /orders/{orderId}  -> 200 order lines of the caller's order, 404 otherwise
GET  /health            -> liveness for ECS/ALB; touches neither DynamoDB nor Cognito
Every /orders route requires `Authorization: Bearer <Cognito ID token>`.
"""
import logging
from contextlib import asynccontextmanager
from functools import lru_cache

import boto3
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from .auth import TokenVerifier, bearer_token
from .config import load_settings
from .orders import OrderRepository, ValidationError, parse_items
from .tracing import setup_tracing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("orders_service")

settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("started app_version=%s table=%s user_pool=%s", settings.app_version,
                settings.table_name, settings.user_pool_id)
    yield


app = FastAPI(title="Orders Service", version=settings.app_version, lifespan=lifespan)
setup_tracing(app, settings.app_version)


@lru_cache
def get_repository() -> OrderRepository:
    # One boto3 resource per process; DynamoDB is reached through the VPC gateway endpoint
    table = boto3.resource("dynamodb", region_name=settings.region).Table(settings.table_name)
    return OrderRepository(table)


@lru_cache
def get_verifier() -> TokenVerifier:
    return TokenVerifier(settings)


def customer_id(token: str = Depends(bearer_token), verifier: TokenVerifier = Depends(get_verifier)) -> str:
    return verifier.verify(token)["sub"]


@app.get("/health")
def health():
    return {"status": "ok", "service": "orders", "app_version": settings.app_version}


@app.post("/orders", status_code=201)
async def create_order(request: Request, customer: str = Depends(customer_id),
                       repo: OrderRepository = Depends(get_repository)):
    try:
        items = parse_items(await request.json())
    except ValueError:   # includes json.JSONDecodeError
        return JSONResponse(status_code=400, content={"message": "request body must be valid JSON"})
    except ValidationError as err:
        logger.info("rejected order: %s", err)
        return JSONResponse(status_code=400, content={"message": str(err)})
    order = repo.save(customer, items)
    logger.info("order created orderId=%s itemCount=%d", order["orderId"], order["itemCount"])
    return order


@app.get("/orders/{order_id}")
def get_order(order_id: str, customer: str = Depends(customer_id),
              repo: OrderRepository = Depends(get_repository)):
    order = repo.get_for_customer(order_id.strip(), customer)
    if order is None:
        return JSONResponse(status_code=404, content={"message": "order not found"})
    return order
