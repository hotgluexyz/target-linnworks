"""Linnworks target sink classes."""

import json
from datetime import datetime, timedelta

from target_linnworks.client import LinnworksSink


def _map_address(address: dict, full_name: str = None, email: str = None, phone: str = None) -> dict:
    """Map a hotglue unified address to a Linnworks address object.

    full_name, email, and phone are passed separately because the unified schema stores
    shipping_name / billing_name / customer_email / shipping_phone as top-level order
    fields, not inside the address object.
    """
    if not address:
        return {}
    return {
        "FullName": full_name or address.get("name") or address.get("full_name"),
        "Company": address.get("company"),
        "Address1": address.get("line1") or address.get("address1"),
        "Address2": address.get("line2") or address.get("address2"),
        "Address3": address.get("line3") or address.get("address3"),
        "Town": address.get("city") or address.get("town"),
        "Region": address.get("state") or address.get("region"),
        "PostCode": address.get("postal_code") or address.get("zip") or address.get("postcode"),
        "Country": address.get("country"),
        "EmailAddress": email or address.get("email"),
        "PhoneNumber": phone or address.get("phone"),
    }


def _map_line_item(item: dict) -> dict:
    """Map a hotglue unified line item to a Linnworks OrderItem object."""
    sku = item.get("sku") or item.get("item_number") or item.get("channel_sku") or ""
    return {
        "TaxCostInclusive": item.get("tax_cost_inclusive", True),
        "UseChannelTax": item.get("use_channel_tax", False),
        "PricePerUnit": float(next((item[k] for k in ("unit_price", "price", "price_per_unit") if item.get(k) is not None), 0)),
        "Qty": round(next((item[k] for k in ("quantity", "qty") if item.get(k) is not None), 1)),
        "TaxRate": float(item.get("tax_rate") or 0),
        "LineDiscount": float(next((item[k] for k in ("discount_amount", "discount", "line_discount") if item.get(k) is not None), 0)),
        "ItemNumber": sku,
        "ChannelSKU": item.get("channel_sku") or sku,
        "IsService": bool(item.get("is_service", False)),
        "ItemTitle": item.get("product_name") or item.get("title") or item.get("name") or item.get("item_title") or sku,
    }


class OrdersSink(LinnworksSink):
    """Writes Orders to Linnworks via the CreateOrders API."""

    name = "Orders"
    endpoint = "/api/Orders/CreateOrders"
    entity = "OrderId"

    def preprocess_record(self, record: dict, context: dict) -> dict:
        config = self.config
        default_source = config.get("default_source", "Hotglue")
        default_subsource = config.get("default_subsource", "Hotglue")

        received_date = (
            record.get("created_at")
            or record.get("received_date")
            or record.get("date_created")
            or datetime.utcnow().isoformat()
        )

        dispatch_by = record.get("dispatch_by") or record.get("requested_date") or record.get("expected_delivery_date")
        if not dispatch_by:
            try:
                parsed = datetime.fromisoformat(received_date.replace("Z", "+00:00"))
            except Exception:
                parsed = datetime.utcnow()
            dispatch_by = (parsed + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")

        line_items_raw = (
            record.get("line_items")
            or record.get("order_items")
            or record.get("items")
            or []
        )
        order_items = [_map_line_item(item) for item in line_items_raw if item]

        if not order_items:
            order_items = [
                {
                    "TaxCostInclusive": True,
                    "UseChannelTax": False,
                    "PricePerUnit": 0.0,
                    "Qty": 1,
                    "TaxRate": 0.0,
                    "LineDiscount": 0.0,
                    "ItemNumber": "UNKNOWN",
                    "ChannelSKU": "UNKNOWN",
                    "IsService": True,
                    "ItemTitle": "Unknown Item",
                }
            ]

        shipping_address = _map_address(
            record.get("shipping_address") or {},
            full_name=record.get("shipping_name") or record.get("customer_name"),
            email=record.get("customer_email"),
            phone=record.get("shipping_phone") or record.get("phone"),
        )
        billing_address = _map_address(
            record.get("billing_address") or record.get("shipping_address") or {},
            full_name=record.get("billing_name") or record.get("shipping_name") or record.get("customer_name"),
            email=record.get("billing_email") or record.get("customer_email"),
            phone=record.get("billing_phone") or record.get("shipping_phone") or record.get("phone"),
        )

        context["_source_id"] = record.get("id")

        payload = {
            "Source": record.get("source") or default_source,
            "SubSource": record.get("subsource") or record.get("sub_source") or default_subsource,
            "ReferenceNumber": (
                record.get("reference_number")
                or record.get("order_number")
                or record.get("number")
                or record.get("id")
            ),
            "ReceivedDate": received_date,
            "DispatchBy": dispatch_by,
            "Currency": record.get("currency"),
            "PaymentStatus": 1 if record.get("paid") else None,
            "OrderItems": order_items,
            "PostalServiceName": (
                record.get("shipping_method")
                or record.get("postal_service_name")
                or next((s.get("carrier") for s in (record.get("shipping_lines") or []) if s), None)
            ),
            "PostageCost": next(
                (record[k] for k in ("shipping_cost", "postage_cost", "total_shipping") if record.get(k) is not None),
                None,
            ),
            "DeliveryAddress": self.clean_payload(shipping_address) or None,
            "BillingAddress": self.clean_payload(billing_address) or None,
        }

        return self.clean_payload(payload)

    def upsert_record(self, record: dict, context: dict) -> tuple:
        source_id = context.get("_source_id")
        location = self.config.get("location", "Default")

        response = self.linnworks_post(
            self.endpoint,
            {
                "orders": json.dumps([record]),
                "location": location,
            },
        )

        order_ids = response.json()
        order_id = order_ids[0] if order_ids else None

        if order_id and source_id:
            self.linnworks_post(
                "/api/Orders/SetExtendedProperties",
                {
                    "orderId": order_id,
                    "extendedProperties": json.dumps(
                        [{"Name": "SourceOrderId", "Value": source_id, "Type": "Attribute"}]
                    ),
                },
            )

        return order_id, bool(order_id), {}
