"""Order validation and DynamoDB access - ported from Project 3 (CreateOrder / GetOrder Lambdas)."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from boto3.dynamodb.conditions import Key

MAX_ITEMS = 25   # also DynamoDB's BatchWriteItem limit per request


class ValidationError(Exception):
    pass


def parse_items(payload) -> list[dict]:
    if not isinstance(payload, dict):
        raise ValidationError("request body must be a JSON object")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValidationError("'items' must be a non-empty list")
    if len(items) > MAX_ITEMS:
        raise ValidationError(f"an order can contain at most {MAX_ITEMS} items")

    parsed, seen = [], set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValidationError(f"items[{i}] must be an object")
        item_id = item.get("itemId")
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValidationError(f"items[{i}].itemId is required")
        if item_id in seen:
            raise ValidationError(f"duplicate itemId '{item_id}'")
        seen.add(item_id)

        quantity = item.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            raise ValidationError(f"items[{i}].quantity must be a positive integer")
        try:
            unit_price = Decimal(str(item.get("unitPrice")))
        except InvalidOperation:
            raise ValidationError(f"items[{i}].unitPrice must be a number")
        if not unit_price.is_finite() or unit_price < 0:
            raise ValidationError(f"items[{i}].unitPrice must be a non-negative number")

        parsed.append({
            "itemId": item_id,
            "productName": str(item.get("productName", "")),
            "quantity": quantity,
            "unitPrice": unit_price,
        })
    return parsed


class OrderRepository:
    """One DynamoDB item per order line: orderId (HASH) + itemId (RANGE), like Project 3."""

    def __init__(self, table):
        self._table = table

    def save(self, customer_id: str, items: list[dict]) -> dict:
        order_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        with self._table.batch_writer() as batch:
            for item in items:
                batch.put_item(Item={"orderId": order_id, **item, "customerId": customer_id,
                                     "status": "CREATED", "createdAt": created_at})
        total = sum(i["unitPrice"] * i["quantity"] for i in items)
        return {"orderId": order_id, "itemCount": len(items), "total": str(total)}

    def get_for_customer(self, order_id: str, customer_id: str) -> dict | None:
        items = self._table.query(KeyConditionExpression=Key("orderId").eq(order_id))["Items"]
        # Only the owner may read the order; a foreign order is indistinguishable from a missing one
        items = [i for i in items if i.get("customerId") == customer_id]
        if not items:
            return None
        return {
            "orderId": order_id,
            "itemCount": len(items),
            "items": [{
                "itemId": i["itemId"],
                "productName": i.get("productName", ""),
                "quantity": int(i["quantity"]),
                "unitPrice": str(i["unitPrice"]),
                "status": i.get("status"),
                "createdAt": i.get("createdAt"),
            } for i in items],
        }
