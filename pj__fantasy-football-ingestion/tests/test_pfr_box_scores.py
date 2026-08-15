from __future__ import annotations

from fantasy_football_ingestion.jobs import ingest__pfr__box_scores as box_scores


def test_schedule_table_for_season_routes_current_to_inprogress() -> None:
    assert (
        box_scores.schedule_table_for_season(2026, current_season=2026)
        == box_scores.INPROGRESS_SCHEDULES_TABLE
    )
    assert (
        box_scores.schedule_table_for_season(2027, current_season=2026)
        == box_scores.INPROGRESS_SCHEDULES_TABLE
    )
    assert (
        box_scores.schedule_table_for_season(2025, current_season=2026)
        == box_scores.COMPLETED_SCHEDULES_TABLE
    )


def test_build_games_query_current_season_only_reads_inprogress() -> None:
    sql, params = box_scores.build_games_query(
        season_filter_enabled=True,
        season_start=2026,
        season_end=2027,
        current_season=2026,
    )

    assert box_scores.INPROGRESS_SCHEDULES_TABLE in sql
    assert box_scores.COMPLETED_SCHEDULES_TABLE not in sql
    assert params == [2026, 2026, 2027]


def test_build_games_query_historical_only_reads_completed() -> None:
    sql, params = box_scores.build_games_query(
        season_filter_enabled=True,
        season_start=2022,
        season_end=2025,
        current_season=2026,
    )

    assert box_scores.COMPLETED_SCHEDULES_TABLE in sql
    assert box_scores.INPROGRESS_SCHEDULES_TABLE not in sql
    assert params == [2026, 2022, 2025]


def test_build_games_query_mixed_range_unions_both_tables() -> None:
    sql, params = box_scores.build_games_query(
        season_filter_enabled=True,
        season_start=2022,
        season_end=2027,
        current_season=2026,
    )

    assert box_scores.COMPLETED_SCHEDULES_TABLE in sql
    assert box_scores.INPROGRESS_SCHEDULES_TABLE in sql
    assert "UNION ALL" in sql
    assert params == [2026, 2026, 2022, 2027]


def test_game_has_occurred_skips_future_dates() -> None:
    today = "20260815"
    assert box_scores.game_has_occurred({"game_date": "20260815"}, today=today)
    assert box_scores.game_has_occurred({"game_date": "20260814"}, today=today)
    assert not box_scores.game_has_occurred({"game_date": "20260909"}, today=today)
    assert not box_scores.game_has_occurred({"game_date": None}, today=today)
    assert not box_scores.game_has_occurred({}, today=today)
