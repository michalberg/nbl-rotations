"""Generate static HTML pages and JSON data for the visualization."""

import json
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .parser import GameData, Player, parse_time_to_seconds
from .rotations import PlayerRotation
from .ratings import PlayerRating

PROJECT_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = PROJECT_DIR / "templates"
STATIC_DIR = PROJECT_DIR / "static"
DOCS_DIR = PROJECT_DIR / "docs"


@dataclass
class _PbpEvent:
    """Pre-processed PBP event with absolute time."""
    abs_time: float
    team_number: int
    shirt_number: str
    action_type: str
    sub_type: str
    success: int
    points: int  # 0, 1, 2, or 3


def _build_pbp_events(game: GameData) -> list[_PbpEvent]:
    """Build list of pre-processed PBP events with absolute time."""
    events = []
    for event in game.events:
        if event.team_number == 0:
            continue
        points = 0
        if event.action_type == "2pt" and event.success == 1:
            points = 2
        elif event.action_type == "3pt" and event.success == 1:
            points = 3
        elif event.action_type == "freethrow" and event.success == 1:
            points = 1
        abs_time = parse_time_to_seconds(event.game_time, event.period)
        events.append(_PbpEvent(
            abs_time=abs_time,
            team_number=event.team_number,
            shirt_number=event.shirt_number,
            action_type=event.action_type,
            sub_type=event.sub_type,
            success=event.success,
            points=points,
        ))
    return events


def _empty_stats() -> dict:
    return {"pts": 0, "reb": 0, "ast": 0, "stl": 0, "blk": 0,
            "fgm": 0, "fga": 0, "fg3m": 0, "fg3a": 0,
            "ftm": 0, "fta": 0, "pf": 0, "tov": 0}


def _collect_player_stats(events: list[_PbpEvent], shirt_number: str,
                          team_number: int) -> dict:
    """Collect box score stats from a list of events for a specific player."""
    s = _empty_stats()
    for e in events:
        if e.team_number != team_number or e.shirt_number != shirt_number:
            continue
        if e.action_type in ("2pt", "3pt"):
            s["fga"] += 1
            if e.action_type == "3pt":
                s["fg3a"] += 1
            if e.success == 1:
                s["fgm"] += 1
                s["pts"] += e.points
                if e.action_type == "3pt":
                    s["fg3m"] += 1
        elif e.action_type == "freethrow":
            s["fta"] += 1
            if e.success == 1:
                s["ftm"] += 1
                s["pts"] += 1
        elif e.action_type == "rebound" and e.sub_type in ("offensive", "defensive"):
            s["reb"] += 1
        elif e.action_type == "assist":
            s["ast"] += 1
        elif e.action_type == "steal":
            s["stl"] += 1
        elif e.action_type == "block":
            s["blk"] += 1
        elif e.action_type == "turnover":
            s["tov"] += 1
        elif e.action_type == "foul" and e.sub_type not in ("technical",):
            s["pf"] += 1
    return s


def _build_minute_data(
    rotations: dict[int, list[PlayerRotation]],
    game: GameData,
) -> dict:
    """Build per-minute block data for the visualization."""
    total_minutes = 0
    for p in range(1, game.num_periods + 1):
        total_minutes += 5 if p >= 5 else 10

    pbp_events = _build_pbp_events(game)

    teams = {}
    for tno in [1, 2]:
        team_players = rotations[tno]
        players_data = []

        # Build lookup for firstName/familyName from game.players
        name_lookup = {}
        for p in game.players:
            if p.team_number == tno:
                name_lookup[p.shirt_number] = (p.first_name, p.family_name)

        for pr in team_players:
            minutes = []
            for m in range(total_minutes):
                minute_start = m * 60.0
                minute_end = (m + 1) * 60.0

                # Check if player was on court during this minute
                on_court_seconds = 0.0
                intervals = []

                for stint in pr.stints:
                    overlap_start = max(stint.time_in, minute_start)
                    overlap_end = min(stint.time_out, minute_end)
                    if overlap_start < overlap_end:
                        on_court_seconds += overlap_end - overlap_start
                        intervals.append((overlap_start, overlap_end))

                # Filter events to this minute + on-court time
                plus_minus = 0
                minute_events = []
                for e in pbp_events:
                    if e.abs_time < minute_start or e.abs_time >= minute_end:
                        continue
                    for iv_start, iv_end in intervals:
                        if iv_start <= e.abs_time < iv_end:
                            if e.points > 0:
                                if e.team_number == tno:
                                    plus_minus += e.points
                                else:
                                    plus_minus -= e.points
                            minute_events.append(e)
                            break

                # Collect individual stats from filtered events
                stats = _collect_player_stats(
                    minute_events, pr.shirt_number, tno)

                is_on_court = on_court_seconds > 0
                full_minute = on_court_seconds >= 59.5

                minutes.append({
                    "minute": m,
                    "onCourt": is_on_court,
                    "fullMinute": full_minute,
                    "onCourtSeconds": round(on_court_seconds, 1),
                    "plusMinus": plus_minus,
                    "pts": stats["pts"],
                    "stats": stats,
                })

            # Full-game box score from PBP
            game_stats = _collect_player_stats(pbp_events, pr.shirt_number, tno)
            # Compute +/- from all minutes
            total_pm = sum(m["plusMinus"] for m in minutes if m["onCourt"])

            first_name, family_name = name_lookup.get(
                pr.shirt_number, ("", ""))

            players_data.append({
                "shirtNumber": pr.shirt_number,
                "name": pr.player_name,
                "firstName": first_name,
                "familyName": family_name,
                "isStarter": pr.is_starter,
                "totalSeconds": round(pr.total_seconds, 1),
                "minutes": minutes,
                "gameStats": game_stats,
                "totalPlusMinus": total_pm,
            })

        teams[str(tno)] = players_data

    return teams


def _build_team_pm_per_minute(game: GameData) -> dict:
    """Calculate team +/- per minute for the bottom row."""
    total_minutes = 0
    for p in range(1, game.num_periods + 1):
        total_minutes += 5 if p >= 5 else 10

    result = {"1": [], "2": []}

    last_s1, last_s2 = 0, 0
    # Group events by minute
    events_by_minute: dict[int, list] = {m: [] for m in range(total_minutes)}

    for event in game.events:
        abs_time = parse_time_to_seconds(event.game_time, event.period)
        minute = min(int(abs_time / 60), total_minutes - 1)
        if event.score1 + event.score2 > 0:
            events_by_minute[minute].append((event.score1, event.score2))

    # Compute +/- per minute for each team
    prev_s1, prev_s2 = 0, 0
    for m in range(total_minutes):
        # Find scores at end of this minute
        end_s1, end_s2 = prev_s1, prev_s2
        for s1, s2 in events_by_minute[m]:
            if s1 + s2 >= end_s1 + end_s2:
                end_s1, end_s2 = s1, s2

        delta1 = (end_s1 - prev_s1) - (end_s2 - prev_s2)
        delta2 = -delta1

        result["1"].append(delta1)
        result["2"].append(delta2)

        prev_s1, prev_s2 = end_s1, end_s2

    return result


def _build_period_boundaries(game: GameData) -> list[dict]:
    """Build period boundary info for the x-axis."""
    periods = []
    offset = 0
    for p in range(1, game.num_periods + 1):
        duration = 5 if p >= 5 else 10
        label = f"Q{p}" if p <= 4 else f"OT{p - 4}"
        periods.append({
            "period": p,
            "label": label,
            "startMinute": offset,
            "endMinute": offset + duration,
            "duration": duration,
        })
        offset += duration
    return periods


def build_game_json(
    game: GameData,
    rotations: dict[int, list[PlayerRotation]],
    ratings: dict[int, list[PlayerRating]],
) -> dict:
    """Build the complete JSON data for a game visualization."""
    minute_data = _build_minute_data(rotations, game)
    team_pm = _build_team_pm_per_minute(game)
    periods = _build_period_boundaries(game)

    # Add DNP players (on roster but 0 minutes) to minute_data
    for tno in [1, 2]:
        tno_str = str(tno)
        existing_numbers = {p["shirtNumber"] for p in minute_data[tno_str]}
        name_lookup = {}
        for p in game.players:
            if p.team_number == tno:
                name_lookup[p.shirt_number] = (p.first_name, p.family_name)
        total_minutes = 0
        for p_idx in range(1, game.num_periods + 1):
            total_minutes += 5 if p_idx >= 5 else 10
        for p in game.players:
            if p.team_number == tno and p.shirt_number not in existing_numbers:
                first_name, family_name = name_lookup.get(
                    p.shirt_number, ("", ""))
                minute_data[tno_str].append({
                    "shirtNumber": p.shirt_number,
                    "name": p.name,
                    "firstName": first_name,
                    "familyName": family_name,
                    "isStarter": False,
                    "isDNP": True,
                    "totalSeconds": 0,
                    "minutes": [
                        {"minute": m, "onCourt": False, "fullMinute": False,
                         "onCourtSeconds": 0, "plusMinus": 0, "pts": 0,
                         "stats": _empty_stats()}
                        for m in range(total_minutes)
                    ],
                    "gameStats": _empty_stats(),
                    "totalPlusMinus": 0,
                })

    # Add ratings to players
    ratings_by_player: dict[str, dict] = {}
    for tno, player_ratings in ratings.items():
        for pr in player_ratings:
            key = f"{tno}_{pr.shirt_number}"
            ratings_by_player[key] = {
                "ortg": round(pr.ortg, 1),
                "drtg": round(pr.drtg, 1),
                "netRating": round(pr.net_rating, 1),
            }

    # Build lineup data (who's on court each minute) for tooltip
    total_minutes = periods[-1]["endMinute"] if periods else 40
    lineups = {"1": [], "2": []}
    for tno_str in ["1", "2"]:
        for m in range(total_minutes):
            on_court = []
            for p in minute_data[tno_str]:
                if p["minutes"][m]["onCourt"]:
                    on_court.append(p["name"])
            lineups[tno_str].append(on_court)

    num_ot = game.num_periods - 4 if game.num_periods > 4 else 0

    return {
        "gameId": game.game_id,
        "team1": {
            "name": game.team1_name,
            "code": game.team1_code,
            "score": game.final_score1,
        },
        "team2": {
            "name": game.team2_name,
            "code": game.team2_code,
            "score": game.final_score2,
        },
        "periods": periods,
        "totalMinutes": total_minutes,
        "numOT": num_ot,
        "players": minute_data,
        "teamPlusMinus": team_pm,
        "lineups": lineups,
        "ratings": ratings_by_player,
    }


def _format_date(date_str: str) -> str:
    """Convert YYYY-MM-DD to d.M.YYYY (no leading zeros)."""
    if not date_str or date_str.count("-") != 2:
        return date_str
    parts = date_str.split("-")
    return f"{int(parts[2])}.{int(parts[1])}.{parts[0]}"


def _slugify(text: str) -> str:
    """Convert text to URL-friendly slug: lowercase, no diacritics, hyphens."""
    # Normalize unicode and strip diacritics
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Lowercase, replace non-alphanumeric with hyphens
    slug = ascii_text.lower()
    slug = "".join(c if c.isalnum() else "-" for c in slug)
    # Collapse multiple hyphens, strip leading/trailing
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def _date_to_season(date_str: str) -> str:
    """Convert date to season string. Season starts Sep 1, ends Jun 30.

    "2025-10-15" -> "2025-26", "2026-03-01" -> "2025-26"
    """
    if not date_str or date_str.count("-") != 2:
        return "unknown"
    parts = date_str.split("-")
    year = int(parts[0])
    month = int(parts[1])
    # Sep-Dec -> season starts this year; Jan-Aug -> season started previous year
    if month >= 9:
        start_year = year
    else:
        start_year = year - 1
    end_year = start_year + 1
    return f"{start_year}-{str(end_year)[-2:]}"


def _compute_season_stats(games: list[dict]) -> tuple[dict, dict]:
    """Compute season totals and averages from a list of player game entries.

    Each game entry has: totalSeconds, gameStats, totalPlusMinus.
    DNP games (isDNP=True) are excluded from GP and averages.
    Returns (totals, averages).
    """
    played_games = [g for g in games if not g.get("isDNP", False)]
    gp = len(played_games)
    if gp == 0:
        return {"gp": 0, "totalSeconds": 0, "plusMinus": 0,
                "pts": 0, "reb": 0, "ast": 0, "stl": 0, "blk": 0,
                "fgm": 0, "fga": 0, "fg3m": 0, "fg3a": 0,
                "ftm": 0, "fta": 0, "tov": 0, "pf": 0}, {}

    stat_keys = ["pts", "reb", "ast", "stl", "blk",
                 "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "tov", "pf"]

    totals = {k: 0 for k in stat_keys}
    totals["gp"] = gp
    totals["totalSeconds"] = 0
    totals["plusMinus"] = 0

    for g in played_games:
        totals["totalSeconds"] += g.get("totalSeconds", 0)
        totals["plusMinus"] += g.get("totalPlusMinus", 0)
        gs = g.get("gameStats", {})
        for k in stat_keys:
            totals[k] += gs.get(k, 0)

    # Averages
    avg_seconds = totals["totalSeconds"] / gp
    avg_min = int(avg_seconds // 60)
    avg_sec = int(avg_seconds % 60)

    averages = {
        "minPerGame": f"{avg_min}:{avg_sec:02d}",
        "pts": round(totals["pts"] / gp, 1),
        "reb": round(totals["reb"] / gp, 1),
        "ast": round(totals["ast"] / gp, 1),
        "stl": round(totals["stl"] / gp, 1),
        "blk": round(totals["blk"] / gp, 1),
        "fgPct": round(totals["fgm"] / totals["fga"] * 100, 1) if totals["fga"] else 0.0,
        "fg3Pct": round(totals["fg3m"] / totals["fg3a"] * 100, 1) if totals["fg3a"] else 0.0,
        "ftPct": round(totals["ftm"] / totals["fta"] * 100, 1) if totals["fta"] else 0.0,
        "tov": round(totals["tov"] / gp, 1),
        "pf": round(totals["pf"] / gp, 1),
        "plusMinus": round(totals["plusMinus"] / gp, 1),
    }

    return totals, averages


def generate_site(games_data: list[dict]):
    """Generate the full static site into docs/."""
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "game").mkdir(exist_ok=True)
    (DOCS_DIR / "data").mkdir(exist_ok=True)
    (DOCS_DIR / "js").mkdir(exist_ok=True)
    (DOCS_DIR / "css").mkdir(exist_ok=True)

    # Copy static files
    for js_name in ["rotations-chart.js", "player-chart.js"]:
        js_src = STATIC_DIR / "js" / js_name
        if js_src.exists():
            shutil.copy2(js_src, DOCS_DIR / "js" / js_name)
    css_src = STATIC_DIR / "css" / "style.css"
    if css_src.exists():
        shutil.copy2(css_src, DOCS_DIR / "css" / "style.css")

    # Set up Jinja2
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    # Generate per-game pages
    games_index = []
    for game_json in games_data:
        game_id = game_json["gameId"]

        # Write JSON data
        data_path = DOCS_DIR / "data" / f"{game_id}.json"
        with open(data_path, "w") as f:
            json.dump(game_json, f)

        # Render game page
        date = game_json.get("date", "")
        date_formatted = _format_date(date)
        template = env.get_template("game.html")
        html = template.render(game=game_json, game_id=game_id, date_formatted=date_formatted)
        game_html_path = DOCS_DIR / "game" / f"{game_id}.html"
        with open(game_html_path, "w") as f:
            f.write(html)
        games_index.append({
            "gameId": game_id,
            "team1": game_json["team1"],
            "team2": game_json["team2"],
            "date": date,
            "date_formatted": _format_date(date),
            "numOT": game_json.get("numOT", 0),
        })
        print(f"  Generated: game/{game_id}.html")

    # Sort by date descending (newest first)
    games_index.sort(key=lambda g: g["date"], reverse=True)

    # Render index page
    template = env.get_template("index.html")
    html = template.render(games=games_index)
    with open(DOCS_DIR / "index.html", "w") as f:
        f.write(html)
    print(f"  Generated: index.html ({len(games_index)} games)")


def generate_index(all_games_meta: list[dict]):
    """Regenerate only the index page from games.json metadata.

    Each entry needs: game_id, date, team1, team2, score1, score2.
    Reads existing per-game data files for team names/scores.
    """
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "css").mkdir(exist_ok=True)

    # Copy CSS
    css_src = STATIC_DIR / "css" / "style.css"
    if css_src.exists():
        shutil.copy2(css_src, DOCS_DIR / "css" / "style.css")

    games_index = []
    for g in all_games_meta:
        game_id = g["game_id"]
        # Check if per-game data exists
        data_path = DOCS_DIR / "data" / f"{game_id}.json"
        if data_path.exists():
            with open(data_path) as f:
                game_json = json.load(f)
            date = g.get("date", game_json.get("date", ""))
            games_index.append({
                "gameId": game_id,
                "team1": game_json["team1"],
                "team2": game_json["team2"],
                "date": date,
                "date_formatted": _format_date(date),
                "numOT": game_json.get("numOT", 0),
            })
        else:
            # Use metadata from games.json directly
            date = g.get("date", "")
            games_index.append({
                "gameId": game_id,
                "team1": {"name": g["team1"], "score": g["score1"]},
                "team2": {"name": g["team2"], "score": g["score2"]},
                "date": date,
                "date_formatted": _format_date(date),
                "numOT": 0,
            })

    # Sort by date descending
    games_index.sort(key=lambda x: x["date"], reverse=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("index.html")
    html = template.render(games=games_index)
    with open(DOCS_DIR / "index.html", "w") as f:
        f.write(html)
    print(f"  Generated: index.html ({len(games_index)} games)")


def generate_player_pages(all_games_data: list[dict]):
    """Generate per-player JSON and HTML pages from all game data.

    Aggregates player data across all games, computes season stats,
    and generates individual player pages.
    """
    # Collect player data across games: key = "firstName_familyName"
    players_index: dict[str, dict] = {}

    for game_json in all_games_data:
        game_id = game_json["gameId"]
        date = game_json.get("date", "")
        periods = game_json["periods"]
        num_ot = game_json.get("numOT", 0)

        for tno_str in ["1", "2"]:
            team_info = game_json[f"team{tno_str}"]
            opp_tno = "2" if tno_str == "1" else "1"
            opp_info = game_json[f"team{opp_tno}"]
            is_home = tno_str == "1"
            score = f"{team_info['score']}:{opp_info['score']}"

            for player in game_json["players"][tno_str]:
                first_name = player.get("firstName", "")
                family_name = player.get("familyName", "")
                if not first_name or not family_name:
                    continue

                player_key = f"{first_name}_{family_name}"

                if player_key not in players_index:
                    players_index[player_key] = {
                        "firstName": first_name,
                        "familyName": family_name,
                        "teams": [],
                        "teamNames": [],
                        "games": [],
                    }

                pi = players_index[player_key]
                team_name = team_info["name"]
                if team_name not in pi["teamNames"]:
                    pi["teamNames"].append(team_name)
                    pi["teams"].append({
                        "name": team_name,
                        "code": team_info["code"],
                    })

                # Store game entry for this player
                is_dnp = player.get("isDNP", False)
                pi["games"].append({
                    "gameId": game_id,
                    "date": date,
                    "teamCode": team_info["code"],
                    "teamName": team_name,
                    "opponent": opp_info["name"],
                    "isHome": is_home,
                    "score": score,
                    "numOT": num_ot,
                    "isDNP": is_dnp,
                    "totalSeconds": player["totalSeconds"],
                    "periods": periods,
                    "minutes": player["minutes"] if not is_dnp else [],
                    "gameStats": player["gameStats"],
                    "totalPlusMinus": player["totalPlusMinus"],
                })

    if not players_index:
        print("  No player data to generate.")
        return

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    count = 0
    for player_key, pi in players_index.items():
        # Sort games by date (oldest first for chart, newest for display)
        pi["games"].sort(key=lambda g: g["date"])

        # Determine season from game dates
        dates = [g["date"] for g in pi["games"] if g["date"]]
        season = _date_to_season(dates[0]) if dates else "unknown"

        # Last team for URL
        last_team = pi["games"][-1]["teamName"]
        slug = (f"{_slugify(last_team)}-"
                f"{_slugify(pi['firstName'])}-"
                f"{_slugify(pi['familyName'])}")

        # Compute season stats
        totals, averages = _compute_season_stats(pi["games"])

        # Build player JSON
        player_json = {
            "firstName": pi["firstName"],
            "familyName": pi["familyName"],
            "slug": slug,
            "season": season,
            "currentTeam": last_team,
            "teams": pi["teamNames"],
            "seasonTotals": totals,
            "seasonAverages": averages,
            "games": pi["games"],
        }

        # Write JSON
        season_dir = DOCS_DIR / "data" / "player" / season
        season_dir.mkdir(parents=True, exist_ok=True)
        json_path = season_dir / f"{slug}.json"
        with open(json_path, "w") as f:
            json.dump(player_json, f)

        # Render HTML
        html_dir = DOCS_DIR / "player" / season
        html_dir.mkdir(parents=True, exist_ok=True)
        template = env.get_template("player.html")
        html = template.render(player=player_json)
        html_path = html_dir / f"{slug}.html"
        with open(html_path, "w") as f:
            f.write(html)

        count += 1

    print(f"  Generated: {count} player pages")

    # Generate players index
    _generate_players_index(players_index, env)


def _generate_players_index(players_index: dict, env: Environment):
    """Generate the players index page grouped by team."""
    # Group players by their last team
    teams: dict[str, list] = {}
    for player_key, pi in players_index.items():
        last_team = pi["games"][-1]["teamName"]
        dates = [g["date"] for g in pi["games"] if g["date"]]
        season = _date_to_season(dates[0]) if dates else "unknown"

        slug = (f"{_slugify(last_team)}-"
                f"{_slugify(pi['firstName'])}-"
                f"{_slugify(pi['familyName'])}")

        totals, averages = _compute_season_stats(pi["games"])

        player_entry = {
            "firstName": pi["firstName"],
            "familyName": pi["familyName"],
            "slug": slug,
            "season": season,
            "teamNames": pi["teamNames"],
            "gp": totals.get("gp", 0),
            "averages": averages,
        }

        if last_team not in teams:
            teams[last_team] = []
        teams[last_team].append(player_entry)

    # Sort teams alphabetically, sort players within team by points desc
    sorted_teams = []
    for team_name in sorted(teams.keys()):
        players = sorted(teams[team_name],
                        key=lambda p: p["averages"].get("pts", 0),
                        reverse=True)
        sorted_teams.append({"name": team_name, "players": players})

    # Determine season
    all_seasons = set()
    for pi in players_index.values():
        dates = [g["date"] for g in pi["games"] if g["date"]]
        if dates:
            all_seasons.add(_date_to_season(dates[0]))
    season = sorted(all_seasons)[-1] if all_seasons else "unknown"

    template = env.get_template("players.html")
    html = template.render(teams=sorted_teams, season=season)

    players_dir = DOCS_DIR / "player"
    players_dir.mkdir(parents=True, exist_ok=True)
    with open(players_dir / "index.html", "w") as f:
        f.write(html)
    print(f"  Generated: player/index.html ({sum(len(t['players']) for t in sorted_teams)} players)")


def generate_team_data(all_games_data: list[dict]):
    """Generate per-team JSON with all players and their season stats."""
    # Collect team -> players data
    teams: dict[str, dict] = {}

    for game_json in all_games_data:
        date = game_json.get("date", "")
        for tno_str in ["1", "2"]:
            team_info = game_json[f"team{tno_str}"]
            team_name = team_info["name"]
            team_code = team_info["code"]

            if team_name not in teams:
                teams[team_name] = {
                    "teamName": team_name,
                    "teamCode": team_code,
                    "players": {},
                    "dates": [],
                }

            teams[team_name]["dates"].append(date)

            for player in game_json["players"][tno_str]:
                first_name = player.get("firstName", "")
                family_name = player.get("familyName", "")
                if not first_name or not family_name:
                    continue

                player_key = f"{first_name}_{family_name}"
                if player_key not in teams[team_name]["players"]:
                    teams[team_name]["players"][player_key] = {
                        "firstName": first_name,
                        "familyName": family_name,
                        "games": [],
                    }

                teams[team_name]["players"][player_key]["games"].append({
                    "totalSeconds": player["totalSeconds"],
                    "gameStats": player["gameStats"],
                    "totalPlusMinus": player["totalPlusMinus"],
                })

    count = 0
    for team_name, team_data in teams.items():
        dates = [d for d in team_data["dates"] if d]
        season = _date_to_season(dates[0]) if dates else "unknown"
        team_slug = _slugify(team_name)

        players_list = []
        for player_key, pd in team_data["players"].items():
            # Find last team slug for this player (within this team)
            player_slug = (f"{team_slug}-"
                          f"{_slugify(pd['firstName'])}-"
                          f"{_slugify(pd['familyName'])}")

            totals, averages = _compute_season_stats(pd["games"])

            players_list.append({
                "firstName": pd["firstName"],
                "familyName": pd["familyName"],
                "playerSlug": player_slug,
                "gp": totals.get("gp", 0),
                "seasonTotals": totals,
                "seasonAverages": averages,
            })

        # Sort by total minutes desc
        players_list.sort(
            key=lambda p: p["seasonTotals"].get("totalSeconds", 0),
            reverse=True)

        team_json = {
            "teamName": team_name,
            "teamCode": team_data["teamCode"],
            "slug": team_slug,
            "season": season,
            "players": players_list,
        }

        season_dir = DOCS_DIR / "data" / "team" / season
        season_dir.mkdir(parents=True, exist_ok=True)
        json_path = season_dir / f"{team_slug}.json"
        with open(json_path, "w") as f:
            json.dump(team_json, f)
        count += 1

    print(f"  Generated: {count} team data files")
