"""Create the products table and insert sample rows. Idempotent: safe to run on every deploy.

Run with:  python -m product_service.seed
"""
import logging

import psycopg

from .config import load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("product_service.seed")

SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS products (
        id          SERIAL PRIMARY KEY,
        sku         TEXT UNIQUE NOT NULL,
        name        TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        price       NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
        stock       INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
"""

SAMPLE_PRODUCTS = [
    ("SKU-1001", "Wireless Mouse", "2.4 GHz ergonomic mouse", "24.99", 150),
    ("SKU-1002", "Mechanical Keyboard", "Tenkeyless, brown switches", "89.00", 60),
    ("SKU-1003", "USB-C Hub", "7-in-1, HDMI 4K, 100 W PD", "39.50", 200),
    ("SKU-1004", "27\" Monitor", "QHD IPS, 75 Hz", "229.00", 25),
    ("SKU-1005", "Laptop Stand", "Aluminium, adjustable height", "34.90", 80),
]


def main() -> None:
    settings = load_settings()
    with psycopg.connect(settings.conninfo) as conn:
        conn.execute(SCHEMA_SQL)
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO products (sku, name, description, price, stock) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (sku) DO NOTHING",
                SAMPLE_PRODUCTS,
            )
        total = conn.execute("SELECT count(*) FROM products").fetchone()[0]
    logger.info("seed complete db_host=%s products=%d", settings.db_host, total)


if __name__ == "__main__":
    main()
