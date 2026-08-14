import ast
import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import ARRAY, TEXT

from fantasy_football_ingestion.paths import PROJECT_ROOT

# Edit this list to control which schema.table pairs get published to Neon.
APPROVED_TABLES = [
    "marts.draft_picks",
    "marts.box_scores",
    "data_science_output.player_cohorts",
    "analytics.season_draft_selections_total",
]

# Columns that must remain Postgres text[] on Neon.
# Searchable cohort dimensions are converted to text in the final dbt model.
ARRAY_COLUMNS_BY_TABLE = {
    "data_science_output.player_cohorts": [
        "player_ids",
        "draft_ids",
    ],
}


def _as_list(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, tuple):
        return [str(v) for v in value]
    if isinstance(value, str):
        text_value = value.strip()
        if text_value.startswith("{") and text_value.endswith("}"):
            # Postgres array literal from some drivers: {a,b,c}
            inner = text_value[1:-1]
            if not inner:
                return []
            return [part.strip().strip('"') for part in inner.split(",")]
        if text_value.startswith("[") and text_value.endswith("]"):
            try:
                parsed = ast.literal_eval(text_value)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed]
            except (SyntaxError, ValueError):
                pass
        return [text_value]
    return [str(value)]


def create_engines():
    load_dotenv(PROJECT_ROOT / ".env")
    return (
        create_engine(os.environ["LOCAL_DATABASE_URL"]),
        create_engine(os.environ["NEON_DATABASE_URL"]),
    )


def publish_table(
    local_engine,
    neon_engine,
    source_schema: str,
    source_table: str,
    target_schema: str | None = None,
) -> None:
    target_schema = target_schema or source_schema
    qualified = f"{source_schema}.{source_table}"

    source_name = f"{source_schema}.{source_table}"
    target_name = f"{target_schema}.{source_table}"

    query = f"""
    select *
    from {source_name}
    """

    print(f"Reading local table: {source_name}")
    df = pd.read_sql(query, local_engine)
    print(f"Read {len(df):,} rows")

    array_columns = [col for col in ARRAY_COLUMNS_BY_TABLE.get(qualified, []) if col in df.columns]
    dtype = {}
    for col in array_columns:
        df[col] = df[col].map(_as_list)
        dtype[col] = ARRAY(TEXT())

    with neon_engine.begin() as conn:
        conn.execute(text(f"create schema if not exists {target_schema};"))

    print(f"Writing to Neon: {target_name}")
    df.to_sql(
        name=source_table,
        con=neon_engine,
        schema=target_schema,
        if_exists="replace",
        index=False,
        chunksize=1000,
        dtype=dtype or None,
    )

    with neon_engine.connect() as conn:
        neon_count = conn.execute(
            text(f"""
            select count(*)
            from {target_name}
        """)
        ).scalar()

    print(f"Published {neon_count:,} rows to Neon: {target_name}")


def main() -> None:
    local_engine, neon_engine = create_engines()
    for qualified_name in APPROVED_TABLES:
        if "." not in qualified_name:
            raise ValueError(f"Approved table must be schema.table, got: {qualified_name}")
        schema, table = qualified_name.split(".", 1)
        publish_table(local_engine, neon_engine, schema, table)


if __name__ == "__main__":
    main()
