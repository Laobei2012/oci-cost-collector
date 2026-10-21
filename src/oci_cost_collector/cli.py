"""Load the new OCI cost reports of one tenancy into PostgreSQL, then exit."""

import logging
import os
import sys
from datetime import datetime

import psycopg

from . import db, report, source

log = logging.getLogger("oci_cost_collector")


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, "")
    return value if value else default


def main() -> int:
    logging.basicConfig(
        level=_env("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s"
    )
    tenancy_id = _env("OCI_COST_TENANCY_ID")
    database_url = _env("DATABASE_URL")
    if not tenancy_id or not database_url:
        log.error("Set OCI_COST_TENANCY_ID and DATABASE_URL.")
        return 2
    account = _env("OCI_COST_ACCOUNT", tenancy_id)
    since = _env("OCI_COST_SINCE")
    since = datetime.fromisoformat(since) if since else None
    read_roles = [r.strip() for r in _env("OCI_COST_READ_ROLES", "").split(",") if r.strip()]

    client = source.make_client(
        auth=_env("OCI_COST_AUTH", "instance_principal"),
        region=_env("OCI_COST_REGION"),
        config_file=_env("OCI_CONFIG_FILE"),
        profile=_env("OCI_CONFIG_PROFILE", "DEFAULT"),
    )

    with psycopg.connect(database_url, autocommit=True) as conn:
        db.migrate(conn, read_roles=read_roles)
        done = db.loaded_reports(conn, account)
        todo = [
            r
            for r in source.list_reports(client, tenancy_id)
            if r.name not in done and (since is None or (r.created_at and r.created_at >= since))
        ]
        todo.sort(key=lambda r: r.name)
        log.info("Account %s: %d reports loaded before, %d new.", account, len(done), len(todo))

        reports_total = lines_total = corrections = 0
        for r in todo:
            lines = report.parse(source.download(client, tenancy_id, r.name))
            if db.load_report(conn, account, r.name, r.created_at, lines):
                reports_total += 1
                lines_total += len(lines)
                corrections += sum(1 for line in lines if line["is_correction"])
                log.debug("Loaded %s: %d lines.", r.name, len(lines))

    log.info("Account %s: loaded %d reports with %d lines.", account, reports_total, lines_total)
    if corrections:
        log.info("Account %s: %d of the new lines are corrections.", account, corrections)
    return 0


if __name__ == "__main__":
    sys.exit(main())
