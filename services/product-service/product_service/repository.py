"""Data access for the products table."""
from decimal import Decimal

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

LIST_PRODUCTS_SQL = """
    SELECT id, sku, name, description, price, stock
    FROM products
    ORDER BY id
"""


class ProductRepository:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def list_products(self) -> list[dict]:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(LIST_PRODUCTS_SQL)
            return [_to_json(row) for row in cur.fetchall()]


def _to_json(row: dict) -> dict:
    # NUMERIC comes back as Decimal; prices have 2 decimals, so float is exact enough for JSON
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()}
