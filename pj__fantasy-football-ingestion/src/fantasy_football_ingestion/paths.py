"""Stable project-local paths used by ingestion jobs."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = PROJECT_ROOT / "samples"
PFR_TEAM_ABBREVIATION_MAP_PATH = (
    Path(__file__).resolve().parent / "json_seeds" / "pfr__team_abbreviation_to_name.json"
)
DEFAULT_UNDERDOG_AUTH_PATH = PROJECT_ROOT / "secrets" / "ud_auth.json"
