from __future__ import annotations

import json

from fantasy_football_ingestion.underdog import load_ud_auth


def test_explicit_underdog_auth_path(tmp_path) -> None:
    auth_path = tmp_path / "ud_auth.json"
    expected = {"access_token": "test-only"}
    auth_path.write_text(json.dumps(expected), encoding="utf-8")

    assert load_ud_auth(auth_path) == expected
