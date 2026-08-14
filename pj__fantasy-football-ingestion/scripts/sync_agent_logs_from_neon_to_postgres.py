# TODO: add to master list of shit to run periodically or automate

import json
import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from fantasy_football_ingestion.paths import PROJECT_ROOT


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    neon_engine = create_engine(os.environ["NEON_DATABASE_URL"])
    local_engine = create_engine(os.environ["LOCAL_DATABASE_URL"])

    df = pd.read_sql(
        """
        select payload
        from landing.agent_app_query_logs
        """,
        neon_engine,
    )

    df["payload"] = df["payload"].apply(json.dumps)

    with local_engine.begin() as conn:
        conn.execute(text("create schema if not exists landing;"))
        conn.execute(
            text(
                """
                create table if not exists landing.agent_app_query_logs (
                    payload jsonb not null
                );
                """
            )
        )
        conn.execute(text("truncate table landing.agent_app_query_logs;"))

    df.to_sql(
        "agent_app_query_logs",
        local_engine,
        schema="landing",
        if_exists="append",
        index=False,
    )

    print(f"Copied {len(df):,} agent log rows from Neon to local Postgres.")


if __name__ == "__main__":
    main()
