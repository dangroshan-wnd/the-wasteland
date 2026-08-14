import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from fantasy_football_ingestion.paths import PROJECT_ROOT

SOURCE_TABLE = "marts.draft_picks"
TARGET_SCHEMA = "marts"
TARGET_TABLE = "draft_picks"


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    local_engine = create_engine(os.environ["LOCAL_DATABASE_URL"])
    neon_engine = create_engine(os.environ["NEON_DATABASE_URL"])

    query = f"""
    select *
    from {SOURCE_TABLE}
    """

    print(f"Reading local table: {SOURCE_TABLE}")
    df = pd.read_sql(query, local_engine)
    print(f"Read {len(df):,} rows")

    print(f"Writing to Neon: {TARGET_SCHEMA}.{TARGET_TABLE}")
    df.to_sql(
        name=TARGET_TABLE,
        con=neon_engine,
        schema=TARGET_SCHEMA,
        if_exists="replace",
        index=False,
        chunksize=1000,
    )

    with neon_engine.connect() as conn:
        neon_count = conn.execute(
            text(f"select count(*) from {TARGET_SCHEMA}.{TARGET_TABLE}")
        ).scalar()

    print(f"Published {neon_count:,} rows to Neon: {TARGET_SCHEMA}.{TARGET_TABLE}")


if __name__ == "__main__":
    main()
