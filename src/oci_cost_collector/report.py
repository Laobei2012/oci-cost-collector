"""Parse OCI cost report CSV files.

The parser maps columns by the header line, not by position. OCI adds one
"tags/..." column for each tag key in a tenancy, and the order of these columns
changes between reports. OCI also adds new columns from time to time.
"""

import csv
import gzip
import io
from datetime import datetime
from decimal import Decimal

# CSV column -> database column.
COLUMNS = {
    "lineItem/referenceNo": "reference_no",
    "lineItem/tenantId": "tenant_id",
    "lineItem/intervalUsageStart": "usage_start",
    "lineItem/intervalUsageEnd": "usage_end",
    "product/service": "service",
    "product/compartmentId": "compartment_id",
    "product/compartmentName": "compartment_name",
    "product/region": "region",
    "product/availabilityDomain": "availability_domain",
    "product/resourceId": "resource_id",
    "usage/billedQuantity": "billed_quantity",
    "usage/billedQuantityOverage": "billed_quantity_overage",
    "cost/subscriptionId": "subscription_id",
    "cost/productSku": "product_sku",
    "product/Description": "product_description",
    "cost/unitPrice": "unit_price",
    "cost/unitPriceOverage": "unit_price_overage",
    "cost/myCost": "my_cost",
    "cost/myCostOverage": "my_cost_overage",
    "cost/currencyCode": "currency_code",
    "cost/billingUnitReadable": "billing_unit",
    "cost/skuUnitDescription": "sku_unit_description",
    "cost/overageFlag": "overage_flag",
    "lineItem/isCorrection": "is_correction",
    "lineItem/backreferenceNo": "backreference_no",
    "cost/attributedCost": "attributed_cost",
    "usage/attributedUsage": "attributed_usage",
}

TIMESTAMPS = {"usage_start", "usage_end"}
NUMBERS = {
    "billed_quantity",
    "billed_quantity_overage",
    "unit_price",
    "unit_price_overage",
    "my_cost",
    "my_cost_overage",
    "attributed_cost",
    "attributed_usage",
}
BOOLEANS = {"is_correction"}

TAG_PREFIX = "tags/"


def _value(column: str, raw: str):
    if raw == "":
        return None
    if column in TIMESTAMPS:
        return datetime.fromisoformat(raw)
    if column in NUMBERS:
        return Decimal(raw)
    if column in BOOLEANS:
        return raw.lower() == "true"
    return raw


def parse(data: bytes) -> list[dict]:
    """Return one dict per report line.

    Each dict has the database columns from COLUMNS, plus "line_no" (1 for the
    first data line), "tags" (tag key -> value) and "extra" (unknown column ->
    value). Empty values are left out of "tags" and "extra".
    """
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    header = next(reader, None)
    if header is None:
        return []

    lines = []
    for line_no, row in enumerate(reader, start=1):
        line = {column: None for column in COLUMNS.values()}
        line.update(line_no=line_no, tags={}, extra={})
        # A short row leaves the missing columns at None.
        for name, raw in zip(header, row, strict=False):
            if name in COLUMNS:
                column = COLUMNS[name]
                line[column] = _value(column, raw)
            elif raw == "":
                continue
            elif name.startswith(TAG_PREFIX):
                line["tags"][name.removeprefix(TAG_PREFIX)] = raw
            else:
                line["extra"][name] = raw
        lines.append(line)
    return lines
