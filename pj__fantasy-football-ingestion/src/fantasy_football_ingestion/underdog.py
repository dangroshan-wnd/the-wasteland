import json
import os
from pathlib import Path

from fantasy_football_ingestion.paths import DEFAULT_UNDERDOG_AUTH_PATH, PROJECT_ROOT


def load_ud_auth(path: str | Path | None = None):
    configured_path = path or os.getenv("UD_AUTH_PATH") or DEFAULT_UNDERDOG_AUTH_PATH
    auth_path = Path(configured_path)
    if not auth_path.is_absolute():
        auth_path = PROJECT_ROOT / auth_path
    with auth_path.open(encoding="utf-8") as f:
        return json.load(f)


scoring_types = [
    {"id": "ccf300b0-9197-5951-bd96-cba84ad71e86", "scoring_type_name": "Best Ball"},
]


teams_api_config = {
    "product": "fantasy",
    "product_experience_id": "018e1234-5678-9abc-def0-123456789002",
    "state_config_id": "a3e78728-07c3-46fd-ba1a-123e4624e355",
}


slates = [
    {
        "id": "2b2f64fc-0a14-4d4f-bba7-276d3d9f7f4c",
        "slate_name": "Pre-Draft BestBall 2025",
        "key": "settled_drafts",
    },
    {
        "id": "100fec91-ff4f-4368-bbee-c7fcc07307d2",
        "slate_name": "Summer BestBall 2025",
        "key": "settled_drafts",
    },
    {
        "id": "8d0b005a-00e7-4752-8800-4cb803085350",
        "slate_name": "2024 Season",
        "key": "settled_drafts",
    },
    {
        "id": "0855c4ce-1036-4075-88c0-db8bfab93024",
        "slate_name": "2024 Best Ball Resurrection",
        "key": "settled_drafts",
    },
    {
        "id": "820fc363-a578-49ab-9ba9-d74f1edaddd1",
        "slate_name": "2025 Weeks 5-8 Best Ball",
        "key": "settled_drafts",
    },
    {
        "id": "92107473-549d-4a68-a94c-1ed043790956",
        "slate_name": "2025 Season Weeks 1-14",
        "key": "settled_drafts",
    },
    {
        "id": "8f9df7e5-d6ab-4a51-87e1-f91f5c806912",
        "slate_name": "NFL 2026 Pre-Draft Best Ball",
        "key": "completed_drafts",
    },
    {
        "id": "a9c04e81-1ace-4b16-a31d-4c725a47f16f",
        "slate_name": "NFL 2026 Season",
        "key": "completed_drafts",
    },
]
