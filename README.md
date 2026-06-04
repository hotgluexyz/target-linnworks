# target-linnworks

`target-linnworks` is a Singer target for [Linnworks](https://www.linnworks.com/), a multi-channel order management platform. Built with the [Hotglue Singer SDK](https://github.com/hotgluexyz/HotglueSingerSDK) for Singer Targets.

## Installation

```bash
pip install target-linnworks
```

Install from source:

```bash
pip install git+https://github.com/hotgluexyz/target-linnworks.git
```

## Configuration

| Setting | Required | Description |
|---|---|---|
| `application_id` | Yes | UUID of the Linnworks System Integration application |
| `application_secret` | Yes | Application Secret from the Linnworks developer portal |
| `installation_token` | Yes | Permanent installation token received when the app was installed on the target Linnworks account |
| `location` | No | Linnworks location name used when creating orders and setting stock levels. Defaults to `"Default"` |
| `default_source` | No | Default value for the `Source` field on created orders. Defaults to `"Hotglue"` |
| `default_subsource` | No | Default value for the `SubSource` field on created orders. Defaults to `"Hotglue"` |

Example `config.json`:

```json
{
    "application_id": "<your-application-id>",
    "application_secret": "<your-application-secret>",
    "installation_token": "<your-installation-token>",
    "location": "Default",
    "default_source": "Hotglue",
    "default_subsource": "Hotglue"
}
```

## Source Authentication and Authorization

Linnworks uses a System Integration application model:

1. Create a **System Integration** application at [developer.linnworks.com](https://developer.linnworks.com).
2. Install the application on the target Linnworks account using the installation URL provided in the developer portal. You will receive a permanent **installation token**.
3. The target exchanges the `application_id`, `application_secret`, and `installation_token` for a session token by calling `POST /api/Auth/AuthorizeByApplication`. Session tokens expire after 20 minutes of inactivity and are refreshed automatically.

## Supported Streams

| Stream | Description |
|---|---|
| `Orders` | Creates or updates orders via the `CreateOrders` API. Orders are identified by `Source` + `SubSource` + `ReferenceNumber`; sending the same combination to an unpaid order updates it rather than creating a duplicate. |
| `Products` | Creates or updates inventory items via `AddInventoryItem` / `UpdateInventoryItem`. Stock levels from `available_quantity` are applied via `SetStockLevel`. Products with multiple variants produce one item per variant plus a parent placeholder. |

### Orders field mapping

| Incoming field | Linnworks field |
|---|---|
| `reference_number` / `order_number` / `number` / `id` | `ReferenceNumber` |
| `source` | `Source` (falls back to `default_source` config) |
| `subsource` / `sub_source` | `SubSource` (falls back to `default_subsource` config) |
| `created_at` / `received_date` / `date_created` | `ReceivedDate` |
| `dispatch_by` / `requested_date` / `expected_delivery_date` | `DispatchBy` (defaults to ReceivedDate + 7 days) |
| `currency` | `Currency` |
| `paid` | `PaymentStatus` (1 = paid, omitted = unpaid) |
| `shipping_method` / `postal_service_name` / `shipping_lines[0].carrier` | `PostalServiceName` |
| `shipping_cost` / `postage_cost` / `total_shipping` | `PostageCost` |
| `line_items[].sku` | `OrderItems[].ItemNumber` / `ChannelSKU` |
| `line_items[].product_name` / `title` / `name` | `OrderItems[].ItemTitle` |
| `line_items[].quantity` | `OrderItems[].Qty` |
| `line_items[].unit_price` / `price` | `OrderItems[].PricePerUnit` |
| `line_items[].discount_amount` / `discount` | `OrderItems[].LineDiscount` |
| `line_items[].tax_rate` | `OrderItems[].TaxRate` |
| `billing_address.*` / `billing_name` / `billing_email` | `BillingAddress.*` |
| `shipping_address.*` / `shipping_name` / `customer_email` | `DeliveryAddress.*` |

### Products field mapping

Products are upserted by SKU. A product without variants (or with a single variant) maps to one stock item. A product with multiple variants produces one parent item and one stock item per variant.

| Incoming field | Linnworks field |
|---|---|
| `sku` / `id` | `ItemNumber` (SKU) |
| `name` | `ItemTitle` |
| `description` / `short_description` | `MetaData` |
| `cost` | `PurchasePrice` |
| `category.name` / `categories[0].name` | `CategoryName` |
| `variants[].sku` | `ItemNumber` on the variant stock item |
| `variants[].price` | `RetailPrice` |
| `variants[].cost` | `PurchasePrice` (overrides product-level cost) |
| `variants[].available_quantity` | Stock level via `SetStockLevel` at the configured location |
| `variants[].barcode` | `BarcodeNumber` |
| `variants[].weight` | `Weight` |
| `variants[].width` / `length` / `depth` | `Width` / `Height` / `Depth` |

## Usage

Pipe tap output directly into the target:

```bash
tap-mystore --config tap_config.json | target-linnworks --config config.json
```

Use the sample payloads for a quick smoke test:

```bash
cat sample_payload/orders.singer | target-linnworks --config .secrets/config.json
cat sample_payload/products.singer | target-linnworks --config .secrets/config.json
```

## Developer Resources

Set up a local dev environment:

```bash
python -m venv .venv
.venv/bin/pip install -e . ruff pytest
```

Run the linter:

```bash
.venv/bin/ruff check .
```

Run integration tests (requires `.secrets/config.json`):

```bash
.venv/bin/pytest target_linnworks/tests/
```
