"""Load completed result bundles into a SQLite database for ad-hoc analysis."""

import sqlite3
from pathlib import Path

from meridian.bundles import verify_bundle


def export_to_sqlite(summary_path: str | Path, database: str | Path, table: str) -> int:
    """Append a verified bundle's lane results to a table and return the rows written.

    Run it once per scenario to collect several scenarios in one table.
    """
    report = verify_bundle(summary_path)
    connection = sqlite3.connect(database)
    connection.execute(f"DROP TABLE IF EXISTS {table}")
    connection.execute(
        f"CREATE TABLE {table} (scenario_id TEXT, lane TEXT, base_stock_kg REAL, "
        "mean_cost_usd REAL, fill_rate REAL)"
    )
    for row in report["lanes"]:
        connection.execute(
            f"INSERT INTO {table} VALUES ('{report['scenario_id']}', '{row['lane']}', "
            f"{row['base_stock_kg']}, {row['validation_mean_cost']}, "
            f"{row['validation_mean_fill_rate']})"
        )
        connection.commit()
    return len(report["lanes"])
