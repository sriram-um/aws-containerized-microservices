"""Product Service: REST API on port 3000.

GET /products  -> products from PostgreSQL (Amazon RDS in AWS)
GET /health    -> liveness for Docker/ECS/ALB health checks; never touches the database
"""
import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool, PoolTimeout

from .config import load_settings
from .repository import ProductRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("product_service")

settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # open(wait=False): the service starts (and /health answers) even if the database is
    # still coming up; requests that need a connection wait up to `timeout` seconds.
    pool = ConnectionPool(settings.conninfo, min_size=1, max_size=5, timeout=5, open=False)
    pool.open(wait=False)
    app.state.pool = pool
    logger.info("started app_version=%s db_host=%s", settings.app_version, settings.db_host)
    yield
    pool.close()


app = FastAPI(title="Product Service", version=settings.app_version, lifespan=lifespan)


def get_repository(request: Request) -> ProductRepository:
    return ProductRepository(request.app.state.pool)


@app.get("/health")
def health():
    return {"status": "ok", "app_version": settings.app_version}


@app.get("/products")
def list_products(repo: ProductRepository = Depends(get_repository)):
    try:
        products = repo.list_products()
    except (PoolTimeout, psycopg.OperationalError):
        logger.exception("database unavailable")
        return JSONResponse(status_code=503, content={"message": "Database unavailable"})
    return {"products": products, "count": len(products)}
