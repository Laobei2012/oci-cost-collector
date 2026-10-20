"""Store cost report lines in PostgreSQL."""

from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from .report import COLUMNS

# Any constant works. It keeps two collectors from creating the schema at the same time.
SCHEMA_LOCK = 0x0C1C057

SCHEMA = """
CREATE TABLE IF NOT EXISTS cost_report (
    account     text        NOT NULL,
    name        text        NOT NULL,
    created_at  timestamptz,
    loaded_at   timestamptz NOT NULL DEFAULT now(),
    line_count  integer     NOT NULL,
    PRIMARY KEY (account, name)
);

CREATE TABLE IF NOT EXISTS cost_line (
    account                 text    NOT NULL,
    report_name             text    NOT NULL,
    line_no                 integer NOT NULL,
    reference_no            text,
    tenant_id               text,
    usage_start             timestamptz,
    usage_end               timestamptz,
    service                 text,
    compartment_id          text,
    compartment_name        text,
    region                  text,
    availability_domain     text,
    resource_id             text,
    billed_quantity         numeric,
    billed_quantity_overage numeric,
    subscription_id         text,
    product_sku             text,
    product_description     text,
    unit_price              numeric,
    unit_price_overage      numeric,
    my_cost                 numeric,
    my_cost_overage         numeric,
    currency_code           text,
    billing_unit            text,
    sku_unit_description    text,
    overage_flag            text,
    is_correction           boolean,
    backreference_no        text,
    attributed_cost         numeric,
    attributed_usage        numeric,
    tags                    jsonb   NOT NULL DEFAULT '{}',
    extra                   jsonb   NOT NULL DEFAULT '{}',
    PRIMARY KEY (account, report_name, line_no),
    FOREIGN KEY (account, report_name) REFERENCES cost_report ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS cost_line_usage_start ON cost_line (usage_start, account);

-- OCI delivers the usage of one hour in pieces, over several reports.
-- This view adds the pieces up.
CREATE OR REPLACE VIEW hourly_usage AS
SELECT account,
       usage_start AS hour,
       service,
       compartment_name,
       region,
       resource_id,
       product_sku,
       product_description,
       sku_unit_description,
       currency_code,
       sum(billed_quantity) AS billed_quantity,
       sum(my_cost)         AS my_cost,
       count(*)             AS pieces
FROM cost_line
GROUP BY account, usage_start, service, compartment_name, region, resource_id,
         product_sku, product_description, sku_unit_description, currency_code;
"""

LINE_COLUMNS = ["account", "report_name", "line_no", *COLUMNS.values(), "tags", "extra"]


def migrate(conn: psycopg.Connection) -> None:
    """Create the tables and the view if they do not exist."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK,))
        conn.execute(SCHEMA)


def loaded_reports(conn: psycopg.Connection, account: str) -> set[str]:
    rows = conn.execute("SELECT name FROM cost_report WHERE account = %s", (account,))
    return {name for (name,) in rows}


def load_report(
    conn: psycopg.Connection,
    account: str,
    name: str,
    created_at: datetime | None,
    lines: list[dict],
) -> bool:
    """Store one report and its lines in one transaction.

    Return False, and change nothing, if the report is already in the database.
    """
    with conn.transaction():
        inserted = conn.execute(
            "INSERT INTO cost_report (account, name, created_at, line_count) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING 1",
            (account, name, created_at, len(lines)),
        ).fetchone()
        if inserted is None:
            return False
        with conn.cursor().copy(f"COPY cost_line ({', '.join(LINE_COLUMNS)}) FROM STDIN") as copy:
            for line in lines:
                values = {**line, "account": account, "report_name": name}
                values["tags"] = Jsonb(line["tags"])
                values["extra"] = Jsonb(line["extra"])
                copy.write_row([values[column] for column in LINE_COLUMNS])
    return True
