import gzip
from datetime import UTC, datetime
from decimal import Decimal

from oci_cost_collector import report

# Two reports of one tenancy: the tag columns are in a different order, and the
# second report has a column that the parser does not know.
REPORT_1 = (
    "lineItem/referenceNo,lineItem/intervalUsageStart,product/resourceId,product/Description,"
    "usage/billedQuantity,cost/myCost,lineItem/isCorrection,tags/team,tags/env\n"
    "ref-1,2026-10-18T10:00Z,ocid1.instance.oc1..example,Standard - A1,0.5,0E-18,false,web,prod\n"
    "ref-2,2026-10-18T10:00Z,ocid1.instance.oc1..example,Standard - A1 - Memory,3,,false,,\n"
)
REPORT_2 = (
    "lineItem/referenceNo,lineItem/intervalUsageStart,product/resourceId,product/Description,"
    "usage/billedQuantity,cost/myCost,lineItem/isCorrection,tags/env,tags/team,cost/newColumn\n"
    "ref-1,2026-10-18T10:00Z,ocid1.instance.oc1..example,Standard - A1,"
    "1.5,8.19E-7,true,prod,web,x\n"
)


def test_parse_maps_columns_by_header():
    lines = report.parse(REPORT_1.encode())
    assert len(lines) == 2
    first = lines[0]
    assert first["line_no"] == 1
    assert first["reference_no"] == "ref-1"
    assert first["usage_start"] == datetime(2026, 10, 18, 10, tzinfo=UTC)
    assert first["billed_quantity"] == Decimal("0.5")
    assert first["my_cost"] == 0
    assert first["is_correction"] is False
    assert first["tags"] == {"team": "web", "env": "prod"}
    assert first["extra"] == {}
    assert first["region"] is None


def test_parse_empty_values():
    second = report.parse(REPORT_1.encode())[1]
    assert second["my_cost"] is None
    assert second["tags"] == {}


def test_parse_moved_tags_and_unknown_column():
    line = report.parse(REPORT_2.encode())[0]
    assert line["tags"] == {"env": "prod", "team": "web"}
    assert line["extra"] == {"cost/newColumn": "x"}
    assert line["my_cost"] == Decimal("8.19E-7")
    assert line["is_correction"] is True


def test_parse_gzip_and_bom():
    data = gzip.compress(("﻿" + REPORT_1).encode())
    assert report.parse(data)[0]["reference_no"] == "ref-1"


def test_parse_empty_file():
    assert report.parse(b"") == []
