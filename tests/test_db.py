"""Tests against a real PostgreSQL. Set TEST_DATABASE_URL to run them."""

import os
from decimal import Decimal

import psycopg
import pytest

from oci_cost_collector import db, report
from tests.test_report import REPORT_1, REPORT_2

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not set")


@pytest.fixture
def conn():
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP VIEW IF EXISTS hourly_usage")
        conn.execute("DROP TABLE IF EXISTS cost_line, cost_report")
        db.migrate(conn)
        yield conn


def test_migrate_twice(conn):
    db.migrate(conn)


def test_load_report_once(conn):
    lines = report.parse(REPORT_1.encode())
    assert db.load_report(conn, "a", "r1", None, lines) is True
    assert db.load_report(conn, "a", "r1", None, lines) is False
    assert db.loaded_reports(conn, "a") == {"r1"}
    assert db.loaded_reports(conn, "b") == set()
    assert conn.execute("SELECT count(*) FROM cost_line").fetchone()[0] == 2


def test_hourly_usage_adds_pieces(conn):
    db.load_report(conn, "a", "r1", None, report.parse(REPORT_1.encode()))
    db.load_report(conn, "a", "r2", None, report.parse(REPORT_2.encode()))
    row = conn.execute(
        "SELECT billed_quantity, pieces FROM hourly_usage WHERE product_description = %s",
        ("Standard - A1",),
    ).fetchone()
    assert row == (Decimal("2.0"), 2)


def test_tags_are_stored(conn):
    db.load_report(conn, "a", "r2", None, report.parse(REPORT_2.encode()))
    tags, extra = conn.execute("SELECT tags, extra FROM cost_line").fetchone()
    assert tags == {"env": "prod", "team": "web"}
    assert extra == {"cost/newColumn": "x"}
