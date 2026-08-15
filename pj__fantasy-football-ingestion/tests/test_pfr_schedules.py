from __future__ import annotations

import pandas as pd
import pytest

from fantasy_football_ingestion.jobs.ingest__pfr__inprogress_season_schedules import (
    derive_game_id,
)
from fantasy_football_ingestion.scrapers.pro_football_reference import (
    parse_inprogress_season_schedule,
)

TEAM_ABBR_MAP = {
    "Cincinnati Bengals": "cin",
    "Detroit Lions": "det",
    "New England Patriots": "nwe",
    "Philadelphia Eagles": "phi",
    "Seattle Seahawks": "sea",
    "Dallas Cowboys": "dal",
}


INPROGRESS_HTML = """
<table id="games">
  <thead>
    <tr>
      <th>Week</th><th>Day</th><th>Date</th><th>VisTm</th><th>Pts</th>
      <th></th><th>HomeTm</th><th>Pts</th><th>Time</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Pre1</td><td>Thu</td><td>August 13</td><td>Detroit Lions</td><td>14</td>
      <td>@</td><td>Cincinnati Bengals</td><td>16</td><td>7:00 PM</td>
    </tr>
    <tr>
      <td>1</td><td>Wed</td><td>September 9</td><td>New England Patriots</td><td></td>
      <td>@</td><td>Seattle Seahawks</td><td></td><td>8:20 PM</td>
    </tr>
    <tr>
      <td>18</td><td>Sun</td><td>January 10</td><td>Dallas Cowboys</td><td></td>
      <td></td><td>Philadelphia Eagles</td><td></td><td>1:00 PM</td>
    </tr>
    <tr>
      <td>Pre2</td><td>Sat</td><td>August 22</td><td>Dallas Cowboys</td><td>10</td>
      <td>@</td><td>Seattle Seahawks</td><td>17</td><td>4:00 PM</td>
    </tr>
  </tbody>
</table>
"""


INPROGRESS_UNNAMED_DATE_HTML = """
<table id="games">
  <thead>
    <tr>
      <th>Week</th><th>Day</th><th></th><th>VisTm</th><th>Pts</th>
      <th></th><th>HomeTm</th><th>Pts</th><th>Time</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>1</td><td>Thu</td><td>September 10</td><td>Detroit Lions</td><td>21</td>
      <td>@</td><td>Philadelphia Eagles</td><td>24</td><td>8:20 PM</td>
    </tr>
  </tbody>
</table>
"""


COMPLETED_HTML = """
<table id="games">
  <thead>
    <tr>
      <th>Week</th><th>Day</th><th>Date</th><th>Winner/tie</th><th></th>
      <th>Loser/tie</th><th>PtsW</th><th>PtsL</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>1</td><td>Thu</td><td>2020-09-10</td><td>Kansas City Chiefs</td><td></td>
      <td>Houston Texans</td><td>34</td><td>20</td>
    </tr>
  </tbody>
</table>
"""


def test_parse_inprogress_skips_preseason_and_assigns_season_years() -> None:
    df = parse_inprogress_season_schedule(INPROGRESS_HTML, 2026, TEAM_ABBR_MAP)

    assert df["week"].tolist() == ["1", "18"]
    kickoff = df.iloc[0].to_dict()
    assert kickoff["date"] == "20260909"
    assert kickoff["home_team"] == "Seattle Seahawks"
    assert kickoff["home_abbr"] == "sea"
    assert kickoff["away_team"] == "New England Patriots"
    assert kickoff["away_abbr"] == "nwe"
    assert kickoff["winner"] in {None} or pd.isna(kickoff["winner"])
    assert kickoff["loser"] in {None} or pd.isna(kickoff["loser"])

    finale = df.iloc[1].to_dict()
    assert finale["date"] == "20270110"
    assert finale["home_team"] == "Philadelphia Eagles"
    assert finale["away_team"] == "Dallas Cowboys"


def test_parse_inprogress_unnamed_date_column_and_scores() -> None:
    df = parse_inprogress_season_schedule(INPROGRESS_UNNAMED_DATE_HTML, 2026, TEAM_ABBR_MAP)

    assert len(df) == 1
    game = df.iloc[0].to_dict()
    assert game["date"] == "20260910"
    assert game["winner"] == "Philadelphia Eagles"
    assert game["loser"] == "Detroit Lions"


def test_parse_inprogress_rejects_completed_winner_format() -> None:
    with pytest.raises(ValueError, match="completed Winner/tie format"):
        parse_inprogress_season_schedule(COMPLETED_HTML, 2020, TEAM_ABBR_MAP)


def test_derive_game_id() -> None:
    assert derive_game_id("20260909", "sea") == "202609090sea"
    assert derive_game_id("20260909", None) is None
