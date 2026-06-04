"""Linnworks target sink classes."""

import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

from target_linnworks.client import LinnworksSink


def _parse_float(value) -> Optional[float]:
    """Safely convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _map_address(
    address: dict, 
    full_name: str = None, 
    company: str = None, 
    email: str = None, 
    phone: str = None
) -> dict:
    """
    Maps a hotglue unified address and separately provided fields to a Linnworks address object.

    Parameters:
        address (dict): Hotglue address dictionary (may be None or empty).
        full_name (str, optional): Name provided at order top level.
        company (str, optional): Company provided at order top level.
        email (str, optional): Email provided at order top level.
        phone (str, optional): Phone number provided at order top level.

    Notes:
        - Unified schema stores shipping/billing name, company, email, and phone as top-level order fields.
        - The caller's clean_payload() function is responsible for handling the all-None/all-empty case.

    Returns:
        dict: Linnworks-formatted address object.
    """
    addr = address or {}
    return {
        "FullName": full_name or addr.get("name") or addr.get("full_name"),
        "Company": company or addr.get("company"),
        "Address1": addr.get("line1") or addr.get("address1"),
        "Address2": addr.get("line2") or addr.get("address2"),
        "Address3": addr.get("line3") or addr.get("address3"),
        "Town": addr.get("city") or addr.get("town"),
        "Region": addr.get("state") or addr.get("region"),
        "PostCode": addr.get("postal_code") or addr.get("zip") or addr.get("postcode"),
        "Country": addr.get("country"),
        "EmailAddress": email or addr.get("email"),
        "PhoneNumber": phone or addr.get("phone"),
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
            record.get("shipping_address"),
            full_name=record.get("shipping_name") or record.get("customer_name"),
            company=record.get("shipping_company") or record.get("customer_company"),
            email=record.get("shipping_email") or record.get("customer_email"),
            phone=record.get("shipping_phone") or record.get("phone"),
        )
        billing_address = _map_address(
            record.get("billing_address") or record.get("shipping_address"),
            full_name=record.get("billing_name") or record.get("shipping_name") or record.get("customer_name"),
            company=record.get("billing_company") or record.get("shipping_company") or record.get("customer_company"),
            email=record.get("billing_email") or record.get("shipping_email") or record.get("customer_email"),
            phone=record.get("billing_phone") or record.get("shipping_phone") or record.get("phone"),
        )

        payload = {
            "Source": record.get("source") or default_source,
            "SubSource": record.get("subsource") or record.get("sub_source") or default_subsource,
            "ReferenceNumber": (
                record.get("reference_number")
                or record.get("order_number")
                or record.get("number")
                or record.get("id")
            ),
            "ExternalReference": record.get("id"),
            "ReceivedDate": received_date,
            "DispatchBy": dispatch_by,
            "Currency": record.get("currency"),
            "PaymentStatus": 1 if record.get("paid") else None,
            "OrderItems": order_items,
            "PostalServiceName": (
                record.get("shipping_method")
                or record.get("postal_service_name")
                or record.get("carrier")
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

        if order_id is None:
            # Linnworks returns [] for orders it cannot create or update (e.g. already paid).
            return None, True, {"existing": True}

        return order_id, True, {}


class ProductsSink(LinnworksSink):
    """Writes Products to Linnworks inventory via AddInventoryItem / UpdateInventoryItem.

    Each incoming Product record is upserted as one or more Linnworks stock items:
    - No variants or a single variant: one stock item.
    - Multiple variants: a variation parent plus one item per variant.

    Stock levels (available_quantity on each Variant) are applied via SetStockLevel
    after the item is created or updated.
    """

    name = "Products"

    def preprocess_record(self, record: dict, context: dict) -> dict:
        return record

    def _build_item(
        self,
        sku: str,
        name: str,
        description: str = None,
        purchase_price: float = None,
        retail_price: float = None,
        barcode: str = None,
        weight: float = None,
        width: float = None,
        depth: float = None,
        height: float = None,
        category_name: str = None,
        stock_level: int = None,
    ) -> dict:
        """Build a cleaned Linnworks stock item dict, with an optional _stock_level marker."""
        item = self.clean_payload({
            "ItemNumber": sku,
            "ItemTitle": name,
            "MetaData": description,
            "PurchasePrice": purchase_price,
            "RetailPrice": retail_price,
            "BarcodeNumber": barcode,
            "Weight": weight,
            "Width": width,
            "Depth": depth,
            "Height": height,
            "CategoryName": category_name,
        })
        if stock_level is not None:
            item["_stock_level"] = int(stock_level)
        return item

    def _upsert_item(self, item: dict) -> Optional[str]:
        """Create or update a single Linnworks stock item, then set its stock level if present."""
        stock_level = item.pop("_stock_level", None)
        sku = item.get("ItemNumber")
        if not sku:
            return None

        existing = self._find_item_by_sku(sku)
        if existing:
            item["StockItemId"] = existing["StockItemId"]
            self._request("POST", "/api/Inventory/UpdateInventoryItem", json={"inventoryItem": item})
            item_id = existing["StockItemId"]
        else:
            item["StockItemId"] = str(uuid.uuid4())
            self._request("POST", "/api/Inventory/AddInventoryItem", json={"inventoryItem": item})
            item_id = item["StockItemId"]

        if stock_level is not None:
            location_name = self.config.get("location", "Default")
            location_id = self._get_location_id(location_name)
            if location_id:
                self._request("POST", "/api/Stock/SetStockLevel", json={
                    "stockLevels": [{"SKU": sku, "LocationId": location_id, "Level": stock_level}],
                    "changeSource": "Hotglue",
                })

        return item_id

    def _ensure_variation_group(
        self, product_sku: str, name: str, variant_ids: list
    ) -> Optional[str]:
        """Create or update the Linnworks variation group for a multi-variant product.

        Linnworks variation groups require the parent SKU to be a new identifier that
        does not yet exist as a normal stock item. CreateVariationGroup creates that
        parent internally. On re-runs the parent SKU already exists, so we call
        AddVariationItems instead (which is idempotent for already-linked items).

        Returns the parent's StockItemId (== pkVariationItemId).
        """
        if not product_sku or not variant_ids:
            return None

        existing_parent = self._find_item_by_sku(product_sku)
        if existing_parent:
            self._request("POST", "/api/Stock/AddVariationItems", json={
                "pkVariationItemId": existing_parent["StockItemId"],
                "pkStockItemIds": variant_ids,
            })
            return existing_parent["StockItemId"]

        resp = self._request("POST", "/api/Stock/CreateVariationGroup", json={
            "template": {
                "VariationGroupName": name,
                "ParentSKU": product_sku,
                "VariationItemIds": variant_ids,
            }
        })
        return resp.json().get("pkVariationItemId")

    def upsert_record(self, record: dict, context: dict) -> tuple:
        product_sku = record.get("sku") or record.get("id") or ""
        name = record.get("name") or product_sku
        description = record.get("description") or record.get("short_description")
        cost = _parse_float(record.get("cost"))

        category = record.get("category") or {}
        categories = record.get("categories") or []
        category_name = (
            category.get("name")
            or (categories[0].get("name") if categories else None)
        )

        variants = record.get("variants") or []

        if not variants:
            # No variant data — map the product itself as a single stock item.
            item_id = self._upsert_item(self._build_item(
                sku=product_sku,
                name=name,
                description=description,
                purchase_price=cost,
                category_name=category_name,
            ))
            return item_id, True, {}

        if len(variants) == 1:
            # Single variant — treat as a simple product; prefer variant-level fields.
            v = variants[0]
            item_id = self._upsert_item(self._build_item(
                sku=v.get("sku") or product_sku,
                name=name,
                description=description,
                purchase_price=_parse_float(v.get("cost")) or cost,
                retail_price=_parse_float(v.get("price")),
                barcode=v.get("barcode"),
                weight=_parse_float(v.get("weight")),
                width=_parse_float(v.get("width")),
                depth=_parse_float(v.get("depth")),
                height=_parse_float(v.get("length")),
                category_name=category_name,
                stock_level=v.get("available_quantity"),
            ))
            return item_id, True, {}

        # Multiple variants: upsert each variant item, then link them under a
        # variation group. The group parent (product_sku) is owned by Linnworks and
        # must NOT be pre-created as a normal stock item.
        variant_ids = []
        for v in variants:
            v_sku = v.get("sku")
            if not v_sku or v_sku == product_sku:
                continue
            v_id = self._upsert_item(self._build_item(
                sku=v_sku,
                name=name,
                description=v.get("description") or description,
                purchase_price=_parse_float(v.get("cost")) or cost,
                retail_price=_parse_float(v.get("price")),
                barcode=v.get("barcode"),
                weight=_parse_float(v.get("weight")),
                width=_parse_float(v.get("width")),
                depth=_parse_float(v.get("depth")),
                height=_parse_float(v.get("length")),
                category_name=category_name,
                stock_level=v.get("available_quantity"),
            ))
            if v_id:
                variant_ids.append(v_id)

        group_id = self._ensure_variation_group(product_sku, name, variant_ids)
        return group_id, True, {}
