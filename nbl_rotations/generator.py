"""Generate static HTML pages and JSON data for the visualization."""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .parser import GameData, parse_time_to_seconds
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

            players_data.append({
                "shirtNumber": pr.shirt_number,
                "name": pr.player_name,
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


def generate_site(games_data: list[dict]):
    """Generate the full static site into docs/."""
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "game").mkdir(exist_ok=True)
    (DOCS_DIR / "data").mkdir(exist_ok=True)
    (DOCS_DIR / "js").mkdir(exist_ok=True)
    (DOCS_DIR / "css").mkdir(exist_ok=True)

    # Copy static files
    js_src = STATIC_DIR / "js" / "rotations-chart.js"
    css_src = STATIC_DIR / "css" / "style.css"
    if js_src.exists():
        shutil.copy2(js_src, DOCS_DIR / "js" / "rotations-chart.js")
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
