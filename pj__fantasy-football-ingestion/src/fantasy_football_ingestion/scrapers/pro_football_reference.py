import csv
import json
import os
import random
import re
import time
from io import StringIO

import pandas as pd
import undetected_chromedriver as uc
from bs4 import BeautifulSoup, Comment

from fantasy_football_ingestion.paths import PFR_TEAM_ABBREVIATION_MAP_PATH

#####################################################################################################################
#####################################################################################################################
#####################################################################################################################
#####################################################################################################################
#####################################################################################################################


PLAYER_OFFENSE_FIELDS = (
    "player",
    "team",
    "pass_cmp",
    "pass_att",
    "pass_yds",
    "pass_td",
    "pass_int",
    "rush_att",
    "rush_yds",
    "rush_td",
    "targets",
    "rec",
    "rec_yds",
    "rec_td",
    "fumbles",
    "fumbles_lost",
)

PLAYER_OFFENSE_COUNTING_FIELDS = PLAYER_OFFENSE_FIELDS[2:]


def _parse_int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _parse_player_offense_table(table, date_str):
    """Parse player offense rows by PFR's data-stat identifiers, not column position."""
    header_fields = {
        cell.get("data-stat") for cell in table.select("thead [data-stat]") if cell.get("data-stat")
    }
    missing_fields = set(PLAYER_OFFENSE_FIELDS) - header_fields
    if missing_fields:
        missing = ", ".join(sorted(missing_fields))
        raise ValueError(f"player_offense table is missing expected fields: {missing}")

    output = []
    for table_row in table.select("tbody tr"):
        if "thead" in table_row.get("class", []):
            continue

        row_values = {
            cell.get("data-stat"): cell.get_text(strip=True)
            for cell in table_row.find_all(["th", "td"], recursive=False)
            if cell.get("data-stat")
        }
        player = row_values.get("player")
        if not player or player.lower() == "player":
            continue

        player_stats = {
            field: _parse_int(row_values.get(field)) for field in PLAYER_OFFENSE_COUNTING_FIELDS
        }
        if player_stats["rec"] > player_stats["targets"]:
            raise ValueError(
                f"invalid receiving stats for {player}: "
                f"{player_stats['rec']} receptions on {player_stats['targets']} targets"
            )

        output.append(
            {
                "player": player,
                "team": row_values.get("team", ""),
                "date": date_str,
                **player_stats,
            }
        )

    return output


def scrape_boxscore_from_schedule_row(row, test_mode=True, browser_session=None):
    """
    Expects a single row from dbt_staging.stg__pfr__completed_season_schedules:
    Must include: game_id, week, game_date
    """
    game_id = row["game_id"]
    date = row.get("game_date")

    url = f"https://www.pro-football-reference.com/boxscores/{game_id}.htm"
    print(f"\n🔍 Scraping: {url}")

    try:
        if browser_session is not None:
            html = browser_session.fetch(url, wait_for="player_offense")
        else:
            html = fetch_pfr_html(url, wait_for="player_offense")
    except Exception as e:
        print(f"❌ Failed to load page: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Game metadata
    date_block = soup.find("div", {"class": "scorebox_meta"})
    date_str = date_block.find("div").text.strip() if date_block else date

    team_tags = soup.select(".scorebox strong a")
    if len(team_tags) < 2:
        print("❌ Could not find both team names")
        return []
    away_team_name, home_team_name = [t.text.strip() for t in team_tags]

    print(f"📅 Date: {date_str}")
    print(f"🏈 Teams: {away_team_name} @ {home_team_name}")

    table = find_pfr_table(soup, "player_offense", raw_html=html)
    if table is None:
        table_wrapper = soup.find("div", {"id": "div_player_offense"})
        table = table_wrapper.find("table", {"id": "player_offense"}) if table_wrapper else None
    if not table:
        print("❌ table#player_offense not found")
        return []

    try:
        output = _parse_player_offense_table(table, date_str)
    except ValueError as e:
        print(f"❌ player_offense parsing failed: {e}")
        return []

    print(f"✅ Found {len(output)} player rows in player_offense table")
    print(f"✅ Extracted {len(output)} player stat rows")
    return output


#####################################################################################################################
#####################################################################################################################
#####################################################################################################################
#####################################################################################################################
#####################################################################################################################


def scrape_season_schedule(season):
    with PFR_TEAM_ABBREVIATION_MAP_PATH.open(encoding="utf-8") as f:
        TEAM_ABBR_MAP = json.load(f)

    url = f"https://www.pro-football-reference.com/years/{season}/games.htm"
    print(f"URL: {url}")
    html = fetch_pfr_html(url, wait_for='id="games"')
    soup = BeautifulSoup(html, "html.parser")
    table = find_pfr_table(soup, "games", raw_html=html)
    if table is None:
        print(f"❌ No game table found for {season}")
        return pd.DataFrame()

    try:
        df = pd.read_html(StringIO(str(table)))[0]
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(-1)
        df.columns = [str(col).strip() for col in df.columns]
        print("🧱 Columns:", df.columns.tolist())
        print(df.head(5))
    except Exception as e:
        print(f"❌ pd.read_html failed: {e}")
        return pd.DataFrame()

    if len(df.columns) > 5 and df.columns[5] != "@":
        df = df.rename(columns={df.columns[5]: "@"})

    df = df[df["Winner/tie"].notna() & df["Loser/tie"].notna()]
    df = df.dropna(subset=["Date", "Winner/tie", "Loser/tie"])
    # PFR repeats column headers as rows inside tbody
    df = df[df["Date"].astype(str) != "Date"]
    df = df[~df["Winner/tie"].astype(str).isin(["Winner/tie", "Loser/tie"])]

    games = []

    for _, row in df.iterrows():
        try:
            date_obj = pd.to_datetime(row["Date"])
            date_str = date_obj.strftime("%Y%m%d")
        except Exception as e:
            print(f"⚠️ Failed to parse date: {row['Date']} — {e}")
            continue

        winner = row["Winner/tie"]
        loser = row["Loser/tie"]

        if str(row.get("@", "")).strip() == "@":
            home_team = loser
            away_team = winner
        else:
            home_team = winner
            away_team = loser

        home_abbr = TEAM_ABBR_MAP.get(home_team, None)
        away_abbr = TEAM_ABBR_MAP.get(away_team, None)

        boxscore_url = None
        for html_row in table.find_all("tr"):
            if str(row["Date"]) in str(html_row):
                cell = html_row.find("td", {"data-stat": "boxscore_word"})
                if cell and cell.a and cell.a.get("href"):
                    boxscore_url = f"https://www.pro-football-reference.com{cell.a['href']}"
                break

        games.append(
            {
                "season": season,
                "week": row["Week"],
                "date": date_str,
                "home_team": home_team,
                "home_abbr": home_abbr,
                "away_team": away_team,
                "away_abbr": away_abbr,
                "boxscore_url": boxscore_url,
                "winner": winner,
                "loser": loser,
            }
        )

    print(f"✅ Parsed {len(games)} games for {season}")
    return pd.DataFrame(games)


def _load_pfr_team_abbr_map():
    with PFR_TEAM_ABBREVIATION_MAP_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _read_pfr_games_dataframe(table):
    df = pd.read_html(StringIO(str(table)))[0]
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(-1)
    df.columns = [str(col).strip() for col in df.columns]
    return df


def _inprogress_date_column(df):
    if "Date" in df.columns:
        return "Date"
    unnamed = [col for col in df.columns if col.startswith("Unnamed: 2")]
    if unnamed:
        return unnamed[0]
    raise ValueError(f"in-progress schedule table is missing a date column: {df.columns.tolist()}")


def _parse_inprogress_game_date(raw, season):
    text = "" if raw is None else str(raw).strip()
    if not text or text.lower() == "date":
        return None
    if re.fullmatch(r"\d{8}", text):
        return text
    # PFR in-progress pages emit "September 9" without a year.
    dated = text if re.search(r"\d{4}", text) else f"{text}, {season}"
    parsed = pd.to_datetime(dated, errors="coerce")
    if pd.isna(parsed):
        return None
    year = season + 1 if parsed.month < 8 else season
    return parsed.replace(year=year).strftime("%Y%m%d")


def _optional_int(raw):
    text = "" if raw is None else str(raw).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _is_preseason_week(week):
    text = str(week).strip().lower()
    return text.startswith("pre") or text in {"hof", "hall of fame"}


def _winner_loser_from_scores(home_team, away_team, home_pts, away_pts):
    if home_pts is None or away_pts is None:
        return None, None
    if away_pts > home_pts:
        return away_team, home_team
    if home_pts > away_pts:
        return home_team, away_team
    return home_team, away_team


def _find_boxscore_url(table, date_token):
    if not date_token:
        return None
    for html_row in table.find_all("tr"):
        if str(date_token) not in str(html_row):
            continue
        cell = html_row.find("td", {"data-stat": "boxscore_word"})
        if cell and cell.a and cell.a.get("href"):
            return f"https://www.pro-football-reference.com{cell.a['href']}"
    return None


def parse_inprogress_season_schedule(html, season, team_abbr_map=None):
    """Parse a PFR games table that uses visitor/home columns (in-progress seasons)."""
    team_abbr_map = team_abbr_map if team_abbr_map is not None else _load_pfr_team_abbr_map()
    soup = BeautifulSoup(html, "html.parser")
    table = find_pfr_table(soup, "games", raw_html=html)
    if table is None:
        print(f"❌ No game table found for {season}")
        return pd.DataFrame()

    try:
        df = _read_pfr_games_dataframe(table)
        print("🧱 Columns:", df.columns.tolist())
        print(df.head(5))
    except Exception as e:
        print(f"❌ pd.read_html failed: {e}")
        return pd.DataFrame()

    if "Winner/tie" in df.columns or "Loser/tie" in df.columns:
        raise ValueError("PFR page is in completed Winner/tie format; use scrape_season_schedule")
    if "VisTm" not in df.columns or "HomeTm" not in df.columns:
        raise ValueError(
            f"in-progress schedule table is missing VisTm/HomeTm columns: {df.columns.tolist()}"
        )

    date_col = _inprogress_date_column(df)
    games = []
    for _, row in df.iterrows():
        week = row.get("Week")
        if week is None or _is_preseason_week(week):
            continue
        week_text = str(week).strip()
        if week_text.lower() in {"week", "nan"}:
            continue

        home_team = row.get("HomeTm")
        away_team = row.get("VisTm")
        if pd.isna(home_team) or pd.isna(away_team):
            continue
        home_team = str(home_team).strip()
        away_team = str(away_team).strip()
        if not home_team or not away_team:
            continue
        if home_team in {"HomeTm", "Home"} or away_team in {"VisTm", "Visitor"}:
            continue

        date_str = _parse_inprogress_game_date(row.get(date_col), season)
        if not date_str:
            print(f"⚠️ Failed to parse date: {row.get(date_col)}")
            continue

        home_pts = _optional_int(row.get("Pts.1"))
        away_pts = _optional_int(row.get("Pts"))
        winner, loser = _winner_loser_from_scores(home_team, away_team, home_pts, away_pts)

        games.append(
            {
                "season": season,
                "week": week_text,
                "date": date_str,
                "home_team": home_team,
                "home_abbr": team_abbr_map.get(home_team),
                "away_team": away_team,
                "away_abbr": team_abbr_map.get(away_team),
                "boxscore_url": _find_boxscore_url(table, row.get(date_col)),
                "winner": winner,
                "loser": loser,
            }
        )

    print(f"✅ Parsed {len(games)} in-progress games for {season}")
    return pd.DataFrame(games)


def scrape_inprogress_season_schedule(season):
    url = f"https://www.pro-football-reference.com/years/{season}/games.htm"
    print(f"URL: {url}")
    html = fetch_pfr_html(url, wait_for='id="games"')
    return parse_inprogress_season_schedule(html, season)


############################################################################################################################################################################################################


def find_pfr_table(soup, table_id, raw_html=None):
    table = soup.find("table", {"id": table_id})
    if table is not None:
        return table
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        if table_id not in comment:
            continue
        comment_soup = BeautifulSoup(comment, "html.parser")
        table = comment_soup.find("table", {"id": table_id})
        if table is not None:
            return table
    if raw_html and table_id in raw_html:
        uncommented = re.sub(r"<!--|-->", "", raw_html)
        table = BeautifulSoup(uncommented, "html.parser").find("table", {"id": table_id})
        if table is not None:
            return table
    return None


class _QuietChrome(uc.Chrome):
    """uc.Chrome with a no-op destructor to avoid Windows double-quit noise."""

    def __del__(self):
        pass


def _close_chrome(driver):
    if driver is None:
        return
    try:
        driver.quit()
    except OSError:
        pass


def _make_chrome_options(headless=False):
    options = uc.ChromeOptions()
    options.headless = headless
    # Eager: return when DOM is interactive. PFR pages often never reach
    # "complete" because ads/analytics keep the renderer busy, which surfaces
    # as "Timed out receiving message from renderer" even when content is visible.
    options.page_load_strategy = "eager"
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    return options


def _start_chrome(version_main=None, headless=False):
    from selenium.common.exceptions import SessionNotCreatedException

    try:
        kwargs = {"options": _make_chrome_options(headless=headless)}
        if version_main is not None:
            kwargs["version_main"] = version_main
        return _QuietChrome(**kwargs)
    except SessionNotCreatedException:
        return _QuietChrome(
            options=_make_chrome_options(headless=headless),
            version_main=version_main or 149,
        )


def _cloudflare_pending(driver):
    return "just a moment" in driver.title.lower()


def _fetch_pfr_html(url, wait_for, timeout=60, driver=None):
    """Fetch a PFR page. Returns (html, driver) for session reuse."""
    if driver is None:
        try:
            from curl_cffi import requests as curl_requests

            res = curl_requests.get(url, impersonate="chrome", timeout=30)
            if res.status_code == 200 and wait_for in res.text:
                return res.text, None
            if res.status_code == 200:
                print("⚠️ Page loaded but expected content missing, retrying with Chrome...")
            else:
                print(f"⚠️ HTTP {res.status_code}, retrying with Chrome...")
        except Exception as e:
            print(f"⚠️ curl_cffi failed ({e}), retrying with Chrome...")

    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait

    headless = os.environ.get("PFR_HEADLESS", "").strip().lower() in ("1", "true", "yes")
    version_main = (
        int(os.environ["PFR_CHROME_VERSION_MAIN"])
        if os.environ.get("PFR_CHROME_VERSION_MAIN")
        else None
    )

    own_driver = driver is None
    if own_driver:
        print("🌐 Opening Chrome...")
        if not headless:
            print("   (visible window — required to pass Cloudflare)")
        driver = _start_chrome(version_main, headless=headless)

    try:
        driver.set_page_load_timeout(timeout)
        try:
            driver.get(url)
        except TimeoutException:
            # Renderer timeout is common on PFR player pages: the DOM (and our
            # target content) is often already present while background requests hang.
            html = driver.page_source or ""
            if wait_for not in html and not _cloudflare_pending(driver):
                raise
            print(
                f"Page load timed out; continuing because "
                f"{'Cloudflare is pending' if _cloudflare_pending(driver) else f'{wait_for!r} is present'}."
            )

        if _cloudflare_pending(driver):
            print("⏳ Waiting for Cloudflare check...")
            try:
                WebDriverWait(driver, timeout).until(lambda d: not _cloudflare_pending(d))
            except TimeoutException as e:
                raise Exception(
                    f"❌ Cloudflare check did not complete (title: {driver.title})"
                ) from e

        try:
            WebDriverWait(driver, timeout).until(lambda d: wait_for in d.page_source)
        except TimeoutException as e:
            raise Exception(
                f"❌ PFR page never loaded expected content (title: {driver.title})"
            ) from e

        time.sleep(random.uniform(0.5, 1.5))
        return driver.page_source, driver
    except Exception:
        if own_driver:
            _close_chrome(driver)
        raise


def fetch_pfr_html(url, wait_for, timeout=60):
    """One-shot PFR fetch; opens and closes Chrome if needed."""
    html, driver = _fetch_pfr_html(url, wait_for, timeout=timeout)
    _close_chrome(driver)
    return html


class PfrBrowserSession:
    """Reuse one Chrome session across multiple PFR page fetches."""

    def __init__(self, timeout=60):
        self.timeout = timeout
        self.driver = None

    def fetch(self, url, wait_for):
        html, self.driver = _fetch_pfr_html(url, wait_for, timeout=self.timeout, driver=self.driver)
        return html

    def close(self):
        _close_chrome(self.driver)
        self.driver = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def scrape_team_metadata():  ## for active teams .csv with abbreviations
    url = "https://www.pro-football-reference.com/teams/"
    html = fetch_pfr_html(url, wait_for="teams_active")
    soup = BeautifulSoup(html, "html.parser")

    team_table = find_pfr_table(soup, "teams_active", raw_html=html)
    if team_table is None:
        title_match = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
        title = title_match.group(1).strip() if title_match else "unknown"
        raise Exception(f"❌ Table #teams_active not found (page title: {title})")

    rows = team_table.find_all("tr")
    print(f"🧪 Found {len(rows)} rows in teams_active table")

    teams = []

    for row in rows:
        header = row.find("th", {"data-stat": "team_name"})
        if not header or not header.a:
            continue

        team_name = header.a.text.strip()
        team_slug = header.a["href"].split("/")[2]

        def get_stat(row, stat):
            td = row.find("td", {"data-stat": stat})
            return td.text.strip() if td else None

        first_year = get_stat(row, "year_min")
        last_year = get_stat(row, "year_max")

        wins = get_stat(row, "wins")
        losses = get_stat(row, "losses")
        ties = get_stat(row, "ties")
        av = get_stat(row, "av")

        passer = get_stat(row, "passer")
        rusher = get_stat(row, "rusher")
        receiver = get_stat(row, "receiver")
        coaching = get_stat(row, "coaching")

        playoff_yrs = get_stat(row, "years_playoffs")
        playoff_wins = get_stat(row, "wins_playoffs")
        playoff_losses = get_stat(row, "losses_playoffs")

        championships = get_stat(row, "championships")
        super_bowls = get_stat(row, "championships_super_bowl")
        conf_titles = get_stat(row, "championships_conference")
        div_titles = get_stat(row, "championships_division")

        teams.append(
            {
                "team_name": team_name,
                "pfr_abbr": team_slug,
                "url_slug": team_slug,
                "full_name": team_name,
                "first_season": int(first_year) if first_year and first_year.isdigit() else None,
                "last_season": int(last_year) if last_year and last_year.isdigit() else None,
                "is_active": True,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "av": av,
                "passer": passer,
                "rusher": rusher,
                "receiver": receiver,
                "coaching": coaching,
                "playoff_yrs": playoff_yrs,
                "playoff_wins": playoff_wins,
                "playoff_losses": playoff_losses,
                "championships": championships,
                "super_bowls": super_bowls,
                "conf_titles": conf_titles,
                "div_titles": div_titles,
            }
        )

    df = pd.DataFrame(teams)
    print("🔍 Preview:")
    print(df.head(10))
    print("🧮 Row count:", len(df))
    return df.sort_values(["team_name"])


#####################################################################################################################
#####################################################################################################################
#####################################################################################################################
#####################################################################################################################
#####################################################################################################################


def scrape_players(
    letters="X",
    output_file=None,
    batch_size=5,
    min_to_year=2020,
    skip_urls=None,
    on_player=None,
    max_players=None,
):
    """
    Scrape player information from Pro Football Reference.

    Uses the same visible Chrome + Cloudflare path as schedules/box scores
    (PfrBrowserSession). No User-Agent spoofing — mismatched UAs cause
    Cloudflare checkbox loops.

    Args:
        letters: Letters to scrape (e.g. "F", or full alphabet).
        output_file: Optional CSV path (legacy append-per-letter behavior).
        batch_size: Letters per Chrome session when scraping the full alphabet.
        min_to_year: Only include players whose career extends to this year or later.
        skip_urls: Optional set of player page URLs already in landing (skip detail fetch).
        on_player: Optional callback(player_dict) invoked after each new player is scraped
            (e.g. incremental landing upsert).
        max_players: Optional cap on newly scraped players (stops early when reached).

    Returns:
        list[dict]: Newly scraped player records (excludes skip_urls).
    """
    from tqdm import tqdm

    BASE_URL = "https://www.pro-football-reference.com"

    def parse_player_details(session, url, name):
        try:
            html = session.fetch(url, wait_for="meta")
        except Exception as e:
            # Keep logs short — full Selenium stacktraces are noise here.
            msg = str(e).splitlines()[0] if str(e) else type(e).__name__
            print(f"   Failed to load page for {name}: {msg}")
            return {}

        soup = BeautifulSoup(html, "html.parser")
        meta = soup.select_one("div#meta")
        if not meta:
            print(f"   Meta block not found for {name}")
            return {}

        dob = None
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and "birthDate" in data:
                    dob = data["birthDate"]
                    break
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue

        if not dob:
            birth_span = meta.find("span", attrs={"data-birth": True})
            if birth_span:
                dob = birth_span.get("data-birth", "").strip()

        height = weight = None
        height_span = meta.find("span", string=re.compile(r"\d+-\d+"))
        if height_span:
            height = height_span.get_text().strip()

        weight_span = meta.find("span", string=re.compile(r"\d+lb"))
        if weight_span:
            weight_match = re.search(r"(\d+)lb", weight_span.get_text().strip())
            if weight_match:
                weight = weight_match.group(1) + " lbs"

        if not weight:
            weight_cell = soup.find("td", attrs={"data-stat": "weight"})
            if weight_cell and weight_cell.get_text().strip():
                weight = weight_cell.get_text().strip() + " lbs"

        draft_info = None
        for para in meta.find_all("p"):
            if "Draft" in para.get_text():
                draft_info = re.sub(r"^Draft:\s*", "", para.get_text().strip())
                break

        return {
            "dob": dob,
            "height": height,
            "weight": weight,
            "draft_info": draft_info,
        }

    def scrape_letter(session, letter):
        url = f"{BASE_URL}/players/{letter}/"
        print(f"\nFetching index: {url}")
        try:
            html = session.fetch(url, wait_for="div_players")
        except Exception as e:
            print(f"Error on letter {letter}: {e}")
            return []

        time.sleep(random.uniform(5, 10))
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select("div#div_players > p a")

        eligible_tags = []
        for tag in container:
            name = tag.text.strip()
            if not name:
                continue
            parent = tag.find_parent("p")
            if parent is None:
                continue
            sibling_text = parent.get_text().replace(name, "").strip()
            years = re.search(r"(\d{4})-(\d{4}|\d{2})", sibling_text)
            if not years:
                continue
            to_year = (
                int("20" + years.group(2)) if len(years.group(2)) == 2 else int(years.group(2))
            )
            if to_year >= min_to_year:
                eligible_tags.append((tag, years, sibling_text, to_year))

        skip = skip_urls or set()
        players = []
        skipped = 0
        pbar = tqdm(eligible_tags, desc=f"{letter}", unit="player")
        for tag, years, sibling_text, to_year in pbar:
            name = tag.text.strip()
            full_url = BASE_URL + tag.get("href")
            position = re.search(r"\(([A-Z\-]+)\)", sibling_text)
            from_year = int(years.group(1))
            pbar.set_description(f"{letter} - {name}")

            if full_url in skip:
                skipped += 1
                continue

            player = {
                "name": name,
                "url": full_url,
                "position": position.group(1) if position else None,
                "from_year": from_year,
                "to_year": to_year,
            }
            player.update(parse_player_details(session, full_url, name))
            players.append(player)
            if on_player is not None:
                on_player(player)
            # Newly captured URLs also skip if the same URL appears again this run
            skip.add(full_url)
            if max_players is not None and len(all_players) + len(players) >= max_players:
                break
            time.sleep(random.uniform(10, 15))

        pbar.close()
        print(f"Done with {letter} — {len(players)} new, {skipped} already in landing")
        return players

    def append_csv(players, path):
        if not players:
            return
        keys = sorted(set().union(*(player.keys() for player in players)))
        file_exists = os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            if not file_exists:
                writer.writeheader()
            writer.writerows(players)
        print(f"Exported {len(players)} players to {path}")

    letter_list = list(letters)
    if letters == "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        batches = [
            "".join(letter_list[i : i + batch_size]) for i in range(0, len(letter_list), batch_size)
        ]
    else:
        batches = [letters]

    print(f"Processing {len(letter_list)} letter(s) in {len(batches)} batch(es)")
    print("Using visible Chrome (same path as schedules/box scores)")

    all_players = []
    start_time = time.time()
    hit_max = False

    for batch_num, batch_letters in enumerate(batches, start=1):
        print(f"\nBatch {batch_num}/{len(batches)}: {batch_letters}")
        with PfrBrowserSession() as session:
            for i, letter in enumerate(batch_letters, start=1):
                print(f"\n[{i}/{len(batch_letters)}] Letter: {letter}")
                players = scrape_letter(session, letter)
                if players:
                    all_players.extend(players)
                    if output_file:
                        append_csv(players, output_file)
                else:
                    print(f"No players found for letter {letter}")

                if max_players is not None and len(all_players) >= max_players:
                    hit_max = True
                    print(f"Reached max_players={max_players}, stopping.")
                    break

                if i < len(batch_letters):
                    time.sleep(5)

        if hit_max:
            break

        if batch_num < len(batches):
            print("Waiting 5s before next batch...")
            time.sleep(5)

    print(f"\nCompleted in {(time.time() - start_time) / 60:.1f} minutes")
    print(f"Total players: {len(all_players)}")
    return all_players
