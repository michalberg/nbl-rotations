"""Generate static HTML pages and JSON data for the visualization."""

import json
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .parser import GameData, Player, parse_time_to_seconds
from .rotations import PlayerRotation
from .ratings import PlayerRating
from .lineups import aggregate_season_lineups, compute_season_onoff

PROJECT_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = PROJECT_DIR / "templates"
STATIC_DIR = PROJECT_DIR / "static"
DOCS_DIR = PROJECT_DIR / "docs"


_LAYUP_SUBTYPES = frozenset({
    "layup", "drivinglayup", "reverselayup", "tipinlayup",
    "eurostep", "floatingjumpshot", "hookshot",
})
_DUNK_SUBTYPES = frozenset({
    "dunk", "alleyoopdunk", "tipindunk", "alleyoop",
})


def _shot_group(action_type: str, sub_type: str) -> str:
    """Return shot group: 'layup', 'dunk', 'midrange', or '3pt'."""
    if action_type == "3pt":
        return "3pt"
    if sub_type in _DUNK_SUBTYPES:
        return "dunk"
    if sub_type in _LAYUP_SUBTYPES:
        return "layup"
    return "midrange"


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
    qualifier: list = field(default_factory=list)


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
            qualifier=event.qualifier,
        ))
    return events


def _build_shot_stats(events: list, team_number: int, shirt_number: str = "") -> dict:
    """Compute shot-type and qualifier stats for a team or player.

    Groups:
      layup    – layup family (drivinglayup, reverselayup, tipinlayup, eurostep, floatingjumpshot, hookshot)
      dunk     – dunk family (alleyoop, alleyoopdunk, tipindunk)
      midrange – 2pt jump shots not in the above groups
      3pt      – all three-pointers

    Qualifiers (on 2pt/3pt + FT for pts):
      fastbreak    – fast-break possession
      secondchance – offensive-rebound possession
      fromturnover – after opponent turnover
      paint        – pointsinthepaint (2pt only, has made/att/pts)
      blocked      – shot blocked (missed shots only, att count)
    """
    groups = {
        "layup":    {"made": 0, "att": 0, "pts": 0},
        "dunk":     {"made": 0, "att": 0, "pts": 0},
        "midrange": {"made": 0, "att": 0, "pts": 0},
        "3pt":      {"made": 0, "att": 0, "pts": 0},
    }
    qualifiers = {
        "fastbreak":    {"pts": 0, "fg_att": 0},
        "secondchance": {"pts": 0, "fg_att": 0},
        "fromturnover": {"pts": 0, "fg_att": 0},
        "paint":        {"pts": 0, "made": 0, "att": 0},
        "blocked":      {"att": 0},
    }
    _qmap = {"fastbreak": "fastbreak", "2ndchance": "secondchance", "fromturnover": "fromturnover"}

    for e in events:
        if e.team_number != team_number:
            continue
        if shirt_number and e.shirt_number != shirt_number:
            continue

        # Shot-type grouping (field goals only)
        if e.action_type in ("2pt", "3pt"):
            grp = _shot_group(e.action_type, e.sub_type)
            groups[grp]["att"] += 1
            if e.success == 1:
                groups[grp]["made"] += 1
                groups[grp]["pts"] += e.points

        # Qualifier stats (field goals + free throws contribute pts)
        for q in e.qualifier:
            if q in _qmap:
                key = _qmap[q]
                if e.action_type in ("2pt", "3pt"):
                    qualifiers[key]["fg_att"] += 1
                if e.points > 0:
                    qualifiers[key]["pts"] += e.points
            elif q == "pointsinthepaint" and e.action_type in ("2pt", "3pt"):
                qualifiers["paint"]["att"] += 1
                if e.success == 1:
                    qualifiers["paint"]["made"] += 1
                    qualifiers["paint"]["pts"] += e.points
            elif q == "blocked" and e.action_type in ("2pt", "3pt"):
                qualifiers["blocked"]["att"] += 1

    return {"groups": groups, "qualifiers": qualifiers}


def _compute_team_situational_stats(minute_data: dict, score_timeline: list) -> dict:
    """Compute bench points, biggest lead, and biggest scoring run per team."""
    result = {"1": {}, "2": {}}

    # Bench points: non-starters who actually played
    for tno_str in ["1", "2"]:
        result[tno_str]["benchPts"] = sum(
            p.get("gameStats", {}).get("pts", 0)
            for p in minute_data[tno_str]
            if not p.get("isStarter") and not p.get("isDNP")
        )

    # Biggest lead and biggest scoring run from score timeline
    max_lead = {1: 0, 2: 0}
    max_run = {1: 0, 2: 0}
    cur_run = {1: 0, 2: 0}
    prev_s1, prev_s2 = 0, 0

    for event in score_timeline[1:]:  # skip initial {t:0, s1:0, s2:0}
        s1, s2 = event["s1"], event["s2"]
        d1, d2 = s1 - prev_s1, s2 - prev_s2
        if d1 > 0:
            cur_run[1] += d1
            cur_run[2] = 0
            if cur_run[1] > max_run[1]:
                max_run[1] = cur_run[1]
        if d2 > 0:
            cur_run[2] += d2
            cur_run[1] = 0
            if cur_run[2] > max_run[2]:
                max_run[2] = cur_run[2]
        lead1, lead2 = s1 - s2, s2 - s1
        if lead1 > max_lead[1]:
            max_lead[1] = lead1
        if lead2 > max_lead[2]:
            max_lead[2] = lead2
        prev_s1, prev_s2 = s1, s2

    for tno_str, tno in [("1", 1), ("2", 2)]:
        result[tno_str]["biggestLead"] = max_lead[tno]
        result[tno_str]["biggestRun"] = max_run[tno]

    return result


def _empty_stats() -> dict:
    return {"pts": 0, "reb": 0, "oreb": 0, "dreb": 0, "ast": 0, "stl": 0, "blk": 0,
            "fgm": 0, "fga": 0, "fg2m": 0, "fg2a": 0, "fg3m": 0, "fg3a": 0,
            "ftm": 0, "fta": 0, "pf": 0, "pfd": 0, "technical": 0, "tov": 0}


def _collect_player_stats(events: list[_PbpEvent], shirt_number: str,
                          team_number: int) -> dict:
    """Collect box score stats from a list of events for a specific player."""
    s = _empty_stats()
    for e in events:
        if e.action_type == "2pt" or e.action_type == "3pt":
            if e.team_number != team_number or e.shirt_number != shirt_number:
                continue
            s["fga"] += 1
            if e.action_type == "3pt":
                s["fg3a"] += 1
            else:
                s["fg2a"] += 1
            if e.success == 1:
                s["fgm"] += 1
                s["pts"] += e.points
                if e.action_type == "3pt":
                    s["fg3m"] += 1
                else:
                    s["fg2m"] += 1
        elif e.action_type == "freethrow":
            if e.team_number != team_number or e.shirt_number != shirt_number:
                continue
            s["fta"] += 1
            if e.success == 1:
                s["ftm"] += 1
                s["pts"] += 1
        elif e.action_type == "rebound":
            if e.team_number != team_number or e.shirt_number != shirt_number:
                continue
            if e.sub_type in ("offensive", "defensive"):
                s["reb"] += 1
                if e.sub_type == "offensive":
                    s["oreb"] += 1
                else:
                    s["dreb"] += 1
        elif e.action_type == "assist":
            if e.team_number != team_number or e.shirt_number != shirt_number:
                continue
            s["ast"] += 1
        elif e.action_type == "steal":
            if e.team_number != team_number or e.shirt_number != shirt_number:
                continue
            s["stl"] += 1
        elif e.action_type == "block":
            if e.team_number != team_number or e.shirt_number != shirt_number:
                continue
            s["blk"] += 1
        elif e.action_type == "turnover":
            if e.team_number != team_number or e.shirt_number != shirt_number:
                continue
            s["tov"] += 1
        elif e.action_type == "foul":
            if e.team_number != team_number or e.shirt_number != shirt_number:
                continue
            if e.sub_type == "technical":
                s["technical"] += 1
            else:
                s["pf"] += 1
        elif e.action_type == "foulon":
            if e.team_number != team_number or e.shirt_number != shirt_number:
                continue
            s["pfd"] += 1
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
                    # Use <= to include zero-duration stints (player enters, acts, exits
                    # at the same game-clock second — e.g. fouled in, shoots FTs, subs out)
                    if overlap_start <= overlap_end:
                        on_court_seconds += overlap_end - overlap_start
                        intervals.append((overlap_start, overlap_end))

                # Filter events to this minute + on-court time
                plus_minus = 0
                minute_events = []
                for e in pbp_events:
                    if e.abs_time < minute_start or e.abs_time >= minute_end:
                        continue
                    for iv_start, iv_end in intervals:
                        # Zero-duration interval: match events at exactly that second
                        in_interval = (e.abs_time == iv_start) if iv_start == iv_end \
                            else (iv_start <= e.abs_time < iv_end)
                        if in_interval:
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
            shot_stats = _build_shot_stats(pbp_events, tno, pr.shirt_number)
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
                "rawStints": [
                    {"timeIn": round(s.time_in, 1), "timeOut": round(s.time_out, 1)}
                    for s in pr.stints
                ],
                "gameStats": game_stats,
                "shotStats": shot_stats,
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
                if p["minutes"][m]["onCourtSeconds"] > 30:
                    on_court.append(p["name"])
            lineups[tno_str].append(on_court)

    num_ot = game.num_periods - 4 if game.num_periods > 4 else 0

    pbp_events_all = _build_pbp_events(game)
    score_timeline = _build_score_timeline(game)
    team_shot_stats = {
        "1": _build_shot_stats(pbp_events_all, 1),
        "2": _build_shot_stats(pbp_events_all, 2),
    }
    situational = _compute_team_situational_stats(minute_data, score_timeline)
    for tno_str in ["1", "2"]:
        team_shot_stats[tno_str].update(situational[tno_str])

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
        "assistPairs": _build_assist_pairs(game),
        "scoreTimeline": score_timeline,
        "teamShotStats": team_shot_stats,
    }


def _build_score_timeline(game: GameData) -> list[dict]:
    """Score at each scoring event: [{t, s1, s2}, ...] starting from 0:0."""
    timeline: list[dict] = [{"t": 0.0, "s1": 0, "s2": 0}]
    last_s1, last_s2 = 0, 0
    for e in game.events:
        s1, s2 = e.score1, e.score2
        if s1 + s2 > 0 and (s1 != last_s1 or s2 != last_s2):
            # Skip stale/out-of-order events (FIBA API sometimes appends late corrections
            # with old scores — basketball scores are monotonically non-decreasing)
            if s1 < last_s1 or s2 < last_s2:
                continue
            t = parse_time_to_seconds(e.game_time, e.period)
            timeline.append({"t": round(t, 1), "s1": s1, "s2": s2})
            last_s1, last_s2 = s1, s2
    return timeline


def _format_date(date_str: str) -> str:
    """Convert YYYY-MM-DD to d.M.YYYY (no leading zeros)."""
    if not date_str or date_str.count("-") != 2:
        return date_str
    parts = date_str.split("-")
    return f"{int(parts[2])}.{int(parts[1])}.{parts[0]}"


def _compute_stints(player: dict) -> list[tuple]:
    """Return list of (start_min, end_min, length_min) for each true on-court stint.

    Uses rawStints (exact seconds) when available — correctly handles substitutions
    at minute boundaries. Falls back to minute-bucket heuristic for old data.
    Quarter/OT breaks are NOT interruptions — only substitutions are.
    """
    raw = player.get("rawStints") if isinstance(player, dict) else None
    if raw:
        # Sort by start time, then merge adjacent stints with gap ≤ 2s
        # (technical substitutions at period breaks have gap = 0)
        valid = sorted(
            [(s["timeIn"], s["timeOut"]) for s in raw if s["timeOut"] > s["timeIn"]],
            key=lambda x: x[0],
        )
        if not valid:
            return []
        merged = [list(valid[0])]
        for t_in, t_out in valid[1:]:
            if t_in - merged[-1][1] <= 2.0:
                merged[-1][1] = max(merged[-1][1], t_out)
            else:
                merged.append([t_in, t_out])
        stints = []
        for t_in, t_out in merged:
            start_min = int(t_in / 60)
            end_min = int((t_out - 0.001) / 60)
            length = end_min - start_min + 1
            if length > 0:
                stints.append((start_min, end_min, length))
        return stints
    # Fallback: minute buckets (less accurate at substitution boundaries)
    minutes_data = player.get("minutes", []) if isinstance(player, dict) else player
    on_court = [m["minute"] for m in minutes_data if m.get("onCourt")]
    if not on_court:
        return []
    stints = []
    cur_start = on_court[0]
    cur_end = on_court[0]
    for i in range(1, len(on_court)):
        if on_court[i] == on_court[i - 1] + 1:
            cur_end = on_court[i]
        else:
            stints.append((cur_start, cur_end, cur_end - cur_start + 1))
            cur_start = on_court[i]
            cur_end = on_court[i]
    stints.append((cur_start, cur_end, cur_end - cur_start + 1))
    return stints


def _compute_shared_seconds(stints1: list, stints2: list) -> float:
    """Compute total overlapping seconds between two sets of raw stints."""
    total = 0.0
    for s1 in stints1:
        for s2 in stints2:
            overlap = min(s1["timeOut"], s2["timeOut"]) - max(s1["timeIn"], s2["timeIn"])
            if overlap > 0:
                total += overlap
    return total


def _build_assist_pairs(game: "GameData") -> list[dict]:
    """Extract passer→scorer assist pairs from PBP events (sequential matching).

    Each assist event follows the made shot it belongs to in the PBP stream.
    We track the last successful field goal per team and link it to the next assist.
    """
    from .parser import Event as _Event
    last_made: dict[int, _Event | None] = {1: None, 2: None}
    pairs: dict[tuple, dict] = {}  # (tno, passer_shirt, scorer_shirt) -> stats

    for event in game.events:  # already sorted ascending by actionNumber
        tno = event.team_number
        if tno not in (1, 2):
            continue
        if event.action_type in ("2pt", "3pt") and event.success == 1:
            last_made[tno] = event
        elif event.action_type == "assist":
            shot = last_made[tno]
            if shot and shot.shirt_number and event.shirt_number:
                key = (tno, event.shirt_number, shot.shirt_number)
                if key not in pairs:
                    pairs[key] = {"ast": 0, "ast2": 0, "ast3": 0, "pts": 0}
                p = pairs[key]
                p["ast"] += 1
                pts = 3 if shot.action_type == "3pt" else 2
                p["pts"] += pts
                if shot.action_type == "3pt":
                    p["ast3"] += 1
                else:
                    p["ast2"] += 1

    result = []
    for (tno, passer_shirt, scorer_shirt), stats in pairs.items():
        result.append({"tno": tno, "passer_shirt": passer_shirt,
                        "scorer_shirt": scorer_shirt, **stats})
    return result


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
                "pts": 0, "reb": 0, "oreb": 0, "dreb": 0, "ast": 0, "stl": 0, "blk": 0,
                "fgm": 0, "fga": 0, "fg2m": 0, "fg2a": 0, "fg3m": 0, "fg3a": 0,
                "ftm": 0, "fta": 0, "tov": 0, "pf": 0, "pfd": 0, "technical": 0}, {}

    stat_keys = ["pts", "reb", "oreb", "dreb", "ast", "stl", "blk",
                 "fgm", "fga", "fg2m", "fg2a", "fg3m", "fg3a",
                 "ftm", "fta", "tov", "pf", "pfd", "technical"]

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
        "oreb": round(totals["oreb"] / gp, 1),
        "dreb": round(totals["dreb"] / gp, 1),
        "ast": round(totals["ast"] / gp, 1),
        "stl": round(totals["stl"] / gp, 1),
        "blk": round(totals["blk"] / gp, 1),
        "fgPct": round(totals["fgm"] / totals["fga"] * 100, 1) if totals["fga"] else 0.0,
        "fg2Pct": round(totals["fg2m"] / totals["fg2a"] * 100, 1) if totals["fg2a"] else 0.0,
        "fg3Pct": round(totals["fg3m"] / totals["fg3a"] * 100, 1) if totals["fg3a"] else 0.0,
        "ftPct": round(totals["ftm"] / totals["fta"] * 100, 1) if totals["fta"] else 0.0,
        "tov": round(totals["tov"] / gp, 1),
        "pf": round(totals["pf"] / gp, 1),
        "pfd": round(totals["pfd"] / gp, 1),
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
        nav_season = _date_to_season(date)
        template = env.get_template("game.html")
        html = template.render(
            game=game_json, game_id=game_id, date_formatted=date_formatted,
            nav_base="../", nav_active="games", nav_season=nav_season,
        )
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
    nav_season = _date_to_season(games_index[0]["date"]) if games_index else "2025-26"
    template = env.get_template("index.html")
    html = template.render(
        games=games_index,
        nav_base="", nav_active="games", nav_season=nav_season,
    )
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
    nav_season = _date_to_season(games_index[0]["date"]) if games_index else "2025-26"
    template = env.get_template("index.html")
    html = template.render(
        games=games_index,
        nav_base="", nav_active="games", nav_season=nav_season,
    )
    with open(DOCS_DIR / "index.html", "w") as f:
        f.write(html)
    print(f"  Generated: index.html ({len(games_index)} games)")


def generate_player_pages(all_games_data: list[dict]):
    """Generate per-player JSON and HTML pages from all game data.

    Aggregates player data across all games, computes season stats,
    and generates individual player pages.
    """
    # Build full team season records (all games, regardless of player roster)
    team_records: dict[str, dict] = {}
    for game_json in all_games_data:
        for tno_str in ["1", "2"]:
            team_name = game_json[f"team{tno_str}"]["name"]
            opp_tno = "2" if tno_str == "1" else "1"
            won = game_json[f"team{tno_str}"]["score"] > game_json[f"team{opp_tno}"]["score"]
            if team_name not in team_records:
                team_records[team_name] = {"gp": 0, "wins": 0}
            team_records[team_name]["gp"] += 1
            if won:
                team_records[team_name]["wins"] += 1

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
                        "shortName": player.get("name", ""),
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
                    "rawStints": player.get("rawStints", []) if not is_dnp else [],
                    "gameStats": player["gameStats"],
                    "totalPlusMinus": player["totalPlusMinus"],
                })

    if not players_index:
        print("  No player data to generate.")
        return

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    # Precompute lineup / on-off data for player pages
    print("  Computing lineup/on-off stats for player pages…")
    season_onoff = compute_season_onoff(all_games_data)
    season_lineups = aggregate_season_lineups(all_games_data, season_onoff)

    # Aggregate assist pairs per player per team
    # {player_key: {team_name: {"as_passer": {partner_key: {...}}, "as_scorer": {partner_key: {...}}}}}
    player_pairs: dict = {}
    for game_json in all_games_data:
        shirt_to_key: dict = {}    # (tno, shirt) -> player_key
        shirt_to_name: dict = {}   # (tno, shirt) -> display name
        shirt_to_stints: dict = {} # (tno, shirt) -> rawStints
        for tno_str in ["1", "2"]:
            tno = int(tno_str)
            for player in game_json["players"][tno_str]:
                first = player.get("firstName", "")
                family = player.get("familyName", "")
                if not first or not family:
                    continue
                shirt = player["shirtNumber"]
                k = (tno, shirt)
                shirt_to_key[k] = f"{first}_{family}"
                shirt_to_name[k] = f"{first} {family}"
                shirt_to_stints[k] = player.get("rawStints", [])

        for pair in game_json.get("assistPairs", []):
            tno = pair["tno"]
            tno_str = str(tno)
            team_name = game_json[f"team{tno_str}"]["name"]
            pk = (tno, pair["passer_shirt"])
            sk = (tno, pair["scorer_shirt"])
            passer_key = shirt_to_key.get(pk)
            scorer_key = shirt_to_key.get(sk)
            if not passer_key or not scorer_key:
                continue
            shared_s = _compute_shared_seconds(
                shirt_to_stints.get(pk, []), shirt_to_stints.get(sk, []))

            for main_key, role, partner_key, partner_name in [
                (passer_key, "as_passer", scorer_key, shirt_to_name.get(sk, "")),
                (scorer_key, "as_scorer", passer_key, shirt_to_name.get(pk, "")),
            ]:
                if main_key not in player_pairs:
                    player_pairs[main_key] = {}
                if team_name not in player_pairs[main_key]:
                    player_pairs[main_key][team_name] = {"as_passer": {}, "as_scorer": {}}
                role_dict = player_pairs[main_key][team_name][role]
                if partner_key not in role_dict:
                    role_dict[partner_key] = {
                        "name": partner_name, "ast": 0, "ast2": 0,
                        "ast3": 0, "pts": 0, "shared_seconds": 0.0,
                    }
                for stat_k in ("ast", "ast2", "ast3", "pts"):
                    role_dict[partner_key][stat_k] += pair[stat_k]
                role_dict[partner_key]["shared_seconds"] += shared_s

    # Build lookup: player_key -> last team name (for partner slugs)
    player_last_team_lookup: dict[str, str] = {}
    for pk, pi_tmp in players_index.items():
        if pi_tmp["games"]:
            player_last_team_lookup[pk] = pi_tmp["games"][-1]["teamName"]

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

        # Compute derived stats and best games
        gp = totals.get("gp", 0)
        if gp > 0:
            _pts, _reb, _ast = totals["pts"], totals["reb"], totals["ast"]
            _stl, _blk, _tov = totals["stl"], totals["blk"], totals["tov"]
            _fgm, _fga, _fg3m = totals["fgm"], totals["fga"], totals["fg3m"]
            _ftm, _fta = totals["ftm"], totals["fta"]
            per = round((_pts + _reb + _ast + _stl + _blk
                         - (_fga - _fgm) - (_fta - _ftm) - _tov) / gp, 2)
            ts_denom = 2 * (_fga + 0.44 * _fta)
            ts_pct = round(_pts / ts_denom * 100, 1) if ts_denom else 0.0
            efg_pct = round((_fgm + 0.5 * _fg3m) / _fga * 100, 1) if _fga else 0.0
        else:
            per = ts_pct = efg_pct = 0.0

        _best_keys = ["pts", "reb", "oreb", "dreb", "ast", "stl", "blk",
                      "fgm", "fga", "fg3m", "fg3a", "ftm", "fta"]
        best_games = {k: {"value": 0, "game_id": "", "date": "", "opponent": ""}
                      for k in _best_keys}
        best_games["plusMinus"] = {"value": -9999, "game_id": "", "date": "", "opponent": ""}
        dd_count = td_count = fouls_out_count = 0
        for g in pi["games"]:
            if g.get("isDNP"):
                continue
            gs = g.get("gameStats", {})
            pm = g.get("totalPlusMinus", 0)
            gid, gdate, gopp = g["gameId"], g.get("date", ""), g.get("opponent", "")
            for k in _best_keys:
                val = gs.get(k, 0)
                if val > best_games[k]["value"]:
                    best_games[k] = {"value": val, "game_id": gid, "date": gdate, "opponent": gopp}
            if pm > best_games["plusMinus"]["value"]:
                best_games["plusMinus"] = {"value": pm, "game_id": gid, "date": gdate, "opponent": gopp}
            dd_cats = sum(1 for c in ["pts", "reb", "ast", "stl"] if gs.get(c, 0) >= 10)
            if dd_cats >= 3:
                td_count += 1
                dd_count += 1
            elif dd_cats == 2:
                dd_count += 1
            if gs.get("pf", 0) >= 5:
                fouls_out_count += 1

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
            "derived": {"per": per, "tsPct": ts_pct, "efgPct": efg_pct},
            "milestones": {"doubleDoubles": dd_count, "tripleDoubles": td_count,
                           "foulsOut": fouls_out_count},
            "bestGames": best_games,
            "games": pi["games"],
        }

        # Write JSON
        season_dir = DOCS_DIR / "data" / "player" / season
        season_dir.mkdir(parents=True, exist_ok=True)
        json_path = season_dir / f"{slug}.json"
        with open(json_path, "w") as f:
            json.dump(player_json, f)

        # Build condensed games for JS filter
        condensed_games = []
        for g in pi["games"]:
            score_parts = g.get("score", "0:0").split(":")
            won = int(score_parts[0]) > int(score_parts[1]) if len(score_parts) == 2 else False
            entry = {"date": g["date"], "isDNP": g.get("isDNP", False), "won": won,
                     "team": g.get("teamName", "")}
            if not g.get("isDNP"):
                gs = g.get("gameStats", {})
                # Per-quarter points from minute-level data
                minutes = g.get("minutes", [])
                q_pts = {1: 0, 2: 0, 3: 0, 4: 0}
                for pd in g.get("periods", []):
                    pnum = pd.get("period", 0)
                    if 1 <= pnum <= 4:
                        start, end = pd["startMinute"], pd["endMinute"]
                        q_pts[pnum] = sum(
                            m.get("pts", 0) for m in minutes
                            if start <= m["minute"] < end
                        )
                entry.update({
                    "game_id": g["gameId"],
                    "plus_minus": g["totalPlusMinus"],
                    "opponent": g.get("opponent", ""),
                    "score": g.get("score", ""),
                    "isHome": g.get("isHome", False),
                    "q1": q_pts[1], "q2": q_pts[2], "q3": q_pts[3], "q4": q_pts[4],
                    **{k: gs.get(k, 0) for k in [
                        "pts", "reb", "oreb", "dreb", "ast", "stl", "blk", "tov",
                        "pf", "pfd", "technical", "fgm", "fga", "fg2m", "fg2a",
                        "fg3m", "fg3a", "ftm", "fta",
                    ]},
                })
            condensed_games.append(entry)

        # Compute on/off data per team
        short_name = pi.get("shortName", "")
        onoff_data = []
        for team_name in pi["teamNames"]:
            key = f"{_slugify(team_name)}|{short_name}"
            raw = season_onoff.get(key)
            if not raw:
                continue
            on, off = raw["on"], raw["off"]
            if on["poss"] <= 0 or on["opp_poss"] <= 0:
                continue
            on_ortg = round(on["pts"] / on["poss"] * 100, 1)
            on_drtg = round(on["opp_pts"] / on["opp_poss"] * 100, 1)
            on_net = round(on_ortg - on_drtg, 1)
            has_off = off["poss"] > 0 and off["opp_poss"] > 0
            off_ortg = round(off["pts"] / off["poss"] * 100, 1) if has_off else None
            off_drtg = round(off["opp_pts"] / off["opp_poss"] * 100, 1) if has_off else None
            off_net = round(off_ortg - off_drtg, 1) if has_off else None
            delta_ortg = round(on_ortg - off_ortg, 1) if has_off else None
            delta_drtg = round(on_drtg - off_drtg, 1) if has_off else None
            delta_net = round(on_net - off_net, 1) if has_off else None
            onoff_data.append({
                "team": team_name,
                "on_ortg": on_ortg, "on_drtg": on_drtg, "on_net": on_net,
                "off_ortg": off_ortg, "off_drtg": off_drtg, "off_net": off_net,
                "delta_ortg": delta_ortg, "delta_drtg": delta_drtg, "delta_net": delta_net,
                "on_minutes": on["minutes"], "off_minutes": off["minutes"] if has_off else 0,
                "has_off": has_off,
            })

        # Compute best quintets (top 3 by net_rtg, min 10 min)
        best_quintets = []
        for team_name in pi["teamNames"]:
            tslug = _slugify(team_name)
            team_q = season_lineups.get(tslug, {}).get("lineups", {}).get(5, [])
            best_quintets.extend([
                {**q, "team": team_name}
                for q in team_q
                if short_name in q["players"] and q["minutes"] >= 10
            ])
        best_quintets = sorted(best_quintets, key=lambda q: -q["stabilized_net"])[:3]

        # Compute top 10 longest stints for this player
        top_stints = []
        for g in pi["games"]:
            if g.get("isDNP"):
                continue
            for start, end, length in _compute_stints(g):
                top_stints.append({
                    "length": length,
                    "start": start,
                    "end": end,
                    "game_id": g["gameId"],
                    "date": g["date"],
                    "opponent": g["opponent"],
                    "score": g["score"],
                    "is_home": g["isHome"],
                    "num_ot": g.get("numOT", 0),
                })
        top_stints.sort(key=lambda s: -s["length"])
        top_stints = top_stints[:10]

        # Build top assist pairs per team for this player
        player_pairs_out: dict[str, dict] = {}
        if player_key in player_pairs:
            for team_name, team_data in player_pairs[player_key].items():
                def _partner_slug(partner_key: str, fallback_team: str) -> str:
                    pk_parts = partner_key.split("_", 1)
                    p_first = pk_parts[0]
                    p_family = pk_parts[1] if len(pk_parts) > 1 else ""
                    p_team = player_last_team_lookup.get(partner_key, fallback_team)
                    return (f"{_slugify(p_team)}-"
                            f"{_slugify(p_first)}-{_slugify(p_family)}")

                as_passer = []
                for partner_key, d in team_data["as_passer"].items():
                    if d["ast"] < 10:
                        continue
                    shared_min = d["shared_seconds"] / 60.0
                    entry = {
                        "name": d["name"],
                        "slug": _partner_slug(partner_key, team_name),
                        "season": season,
                        "ast": d["ast"],
                        "ast2": d["ast2"], "ast3": d["ast3"], "pts": d["pts"],
                        "shared_min": round(shared_min),
                    }
                    if shared_min >= 5:
                        entry["ast_per36"] = round(d["ast"] / shared_min * 36, 1)
                        entry["pts_per36"] = round(d["pts"] / shared_min * 36, 1)
                    as_passer.append(entry)
                as_passer.sort(key=lambda x: -x["ast"])

                as_scorer = []
                for partner_key, d in team_data["as_scorer"].items():
                    if d["ast"] < 10:
                        continue
                    shared_min = d["shared_seconds"] / 60.0
                    entry = {
                        "name": d["name"],
                        "slug": _partner_slug(partner_key, team_name),
                        "season": season,
                        "ast": d["ast"],
                        "ast2": d["ast2"], "ast3": d["ast3"], "pts": d["pts"],
                        "shared_min": round(shared_min),
                    }
                    if shared_min >= 5:
                        entry["ast_per36"] = round(d["ast"] / shared_min * 36, 1)
                        entry["pts_per36"] = round(d["pts"] / shared_min * 36, 1)
                    as_scorer.append(entry)
                as_scorer.sort(key=lambda x: -x["ast"])

                if as_passer or as_scorer:
                    player_pairs_out[team_name] = {
                        "as_passer": as_passer[:5],
                        "as_scorer": as_scorer[:5],
                    }

        # Render HTML
        html_dir = DOCS_DIR / "player" / season
        html_dir.mkdir(parents=True, exist_ok=True)
        template = env.get_template("player.html")
        html = template.render(
            player=player_json,
            player_games_json=json.dumps(condensed_games, ensure_ascii=False),
            team_records_json=json.dumps(team_records, ensure_ascii=False),
            onoff_json=json.dumps(onoff_data, ensure_ascii=False),
            best_quintets_json=json.dumps(best_quintets, ensure_ascii=False),
            top_stints_json=json.dumps(top_stints, ensure_ascii=False),
            player_pairs_json=json.dumps(player_pairs_out, ensure_ascii=False),
            nav_base="../../", nav_active="players", nav_season=season,
        )
        html_path = html_dir / f"{slug}.html"
        with open(html_path, "w") as f:
            f.write(html)

        count += 1

    print(f"  Generated: {count} player pages")

    # Generate players index
    _generate_players_index(players_index, env, season_onoff)


def _generate_players_index(players_index: dict, env: Environment, season_onoff: dict | None = None):
    """Generate the players index page grouped by team."""
    season_onoff = season_onoff or {}
    # Group players by their last team
    teams: dict[str, list] = {}
    ratings_list: list[dict] = []

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

        # Build one ratings entry per team stint so each row on the stats page
        # (which is keyed by team-based slug) can look up its own on/off data.
        short_name = pi.get("shortName", "")
        if short_name:
            for team_name in pi["teamNames"]:
                team_slug = _slugify(team_name)
                raw = season_onoff.get(f"{team_slug}|{short_name}")
                if not raw or raw["on"]["poss"] <= 0 or raw["on"]["opp_poss"] <= 0:
                    continue
                team_entry_slug = (f"{team_slug}-"
                                   f"{_slugify(pi['firstName'])}-"
                                   f"{_slugify(pi['familyName'])}")
                on, off = raw["on"], raw["off"]
                on_ortg = round(on["pts"] / on["poss"] * 100, 1)
                on_drtg = round(on["opp_pts"] / on["opp_poss"] * 100, 1)
                on_net  = round(on_ortg - on_drtg, 1)
                has_off = off["poss"] > 0 and off["opp_poss"] > 0
                off_ortg = round(off["pts"] / off["poss"] * 100, 1) if has_off else None
                off_drtg = round(off["opp_pts"] / off["opp_poss"] * 100, 1) if has_off else None
                off_net  = round(off_ortg - off_drtg, 1) if has_off else None
                delta_net = round(on_net - off_net, 1) if has_off else None
                ratings_list.append({
                    "first_name":  pi["firstName"],
                    "family_name": pi["familyName"],
                    "slug":        team_entry_slug,
                    "season":      season,
                    "team":        team_name,
                    "on_min":      on["minutes"],
                    "on_ortg":     on_ortg,
                    "on_drtg":     on_drtg,
                    "on_net":      on_net,
                    "off_min":     off["minutes"] if has_off else 0,
                    "off_ortg":    off_ortg,
                    "off_drtg":    off_drtg,
                    "off_net":     off_net,
                    "delta_net":   delta_net,
                })

    ratings_list.sort(key=lambda x: -x["on_net"])

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

    # Save flat player ratings for leaderboard page
    data_dir = DOCS_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / f"player_ratings_{season}.json", "w") as f:
        json.dump(ratings_list, f, ensure_ascii=False)

    template = env.get_template("players.html")
    html = template.render(
        teams=sorted_teams, season=season,
        ratings_json=json.dumps(ratings_list, ensure_ascii=False),
        nav_base="../", nav_active="players", nav_season=season,
    )

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


def generate_stats_pages(docs_path: Path | None = None):
    """Generate player and team stats table pages from season_log.json."""
    from .stats import load_season_log, compute_player_season_stats, compute_team_season_stats

    base = docs_path or DOCS_DIR
    log = load_season_log(base)

    if not log["players"] and not log["teams"]:
        print("  No season log data yet.")
        return

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    # Group by season
    seasons: dict[str, dict] = {}
    for slug, pdata in log["players"].items():
        games = pdata.get("games", [])
        if not games:
            continue
        season = _date_to_season(games[0]["date"])
        if season not in seasons:
            seasons[season] = {"players": {}, "teams": {}}
        seasons[season]["players"][slug] = pdata

    for slug, tdata in log["teams"].items():
        games = tdata.get("games", [])
        if not games:
            continue
        season = _date_to_season(games[0]["date"])
        if season not in seasons:
            seasons[season] = {"players": {}, "teams": {}}
        seasons[season]["teams"][slug] = tdata

    count = 0
    for season, sdata in seasons.items():
        out_dir = base / "stats" / season
        out_dir.mkdir(parents=True, exist_ok=True)

        # Players stats page
        player_stats = [
            compute_player_season_stats(slug, pdata)
            for slug, pdata in sdata["players"].items()
        ]
        player_stats = [p for p in player_stats if p.get("gp", 0) > 0]
        all_teams = sorted({p["team"] for p in player_stats})

        # Load player on/off ratings if available
        ratings_file = base / "data" / f"player_ratings_{season}.json"
        player_ratings = []
        if ratings_file.exists():
            with open(ratings_file) as f:
                player_ratings = json.load(f)

        # Load assist pairs if available
        assist_pairs_file = base / "data" / f"assist_pairs_{season}.json"
        assist_pairs = {}
        if assist_pairs_file.exists():
            with open(assist_pairs_file) as f:
                assist_pairs = json.load(f)

        template = env.get_template("stats_players.html")
        html = template.render(
            season=season,
            teams=all_teams,
            players_json=json.dumps(player_stats, ensure_ascii=False),
            game_meta_json=json.dumps(log["game_meta"], ensure_ascii=False),
            ratings_json=json.dumps(player_ratings, ensure_ascii=False),
            assist_pairs_json=json.dumps(assist_pairs, ensure_ascii=False),
            nav_base="../../", nav_active="stats-players", nav_season=season,
        )
        with open(out_dir / "players.html", "w") as f:
            f.write(html)

        # Teams stats page
        team_stats = [
            compute_team_season_stats(slug, tdata)
            for slug, tdata in sdata["teams"].items()
        ]
        team_stats = [t for t in team_stats if t.get("gp", 0) > 0]

        # Build teams_games, augmenting each game with DD/TD counts derived
        # from player game logs (avoids need to reprocess season_log).
        teams_games = {}
        for slug, tdata in sdata["teams"].items():
            team_name = tdata["name"]
            # Build lookup: game_id -> {dd, td, pts20, pts30} for this team's players
            game_dd_td: dict[str, dict] = {}
            for pdata in sdata["players"].values():
                for pg in pdata.get("games", []):
                    if pg.get("isDNP", False) or pg.get("team") != team_name:
                        continue
                    gid = pg.get("game_id", "")
                    if gid not in game_dd_td:
                        game_dd_td[gid] = {"dd": 0, "td": 0, "pts20": 0, "pts30": 0}
                    dd_cats = sum(1 for cat in ["pts", "reb", "ast", "stl"]
                                  if pg.get(cat, 0) >= 10)
                    if dd_cats >= 3:
                        game_dd_td[gid]["td"] += 1
                        game_dd_td[gid]["dd"] += 1
                    elif dd_cats == 2:
                        game_dd_td[gid]["dd"] += 1
                    if pg.get("pts", 0) >= 20:
                        game_dd_td[gid]["pts20"] += 1
                    if pg.get("pts", 0) >= 30:
                        game_dd_td[gid]["pts30"] += 1
            augmented = [
                {**g, **game_dd_td.get(g.get("game_id", ""), {"dd": 0, "td": 0, "pts20": 0, "pts30": 0})}
                for g in tdata.get("games", [])
            ]
            teams_games[slug] = {"name": team_name, "games": augmented}
            # Patch cumulative dd/td/pts20/pts30 into team_stats
            cumul = {
                "dd": sum(v["dd"] for v in game_dd_td.values()),
                "td": sum(v["td"] for v in game_dd_td.values()),
                "pts20": sum(v["pts20"] for v in game_dd_td.values()),
                "pts30": sum(v["pts30"] for v in game_dd_td.values()),
            }
            for ts in team_stats:
                if ts.get("slug") == slug:
                    ts.update(cumul)
                    break

        # Augment teams_games with situational stats from per-game JSON files
        game_json_cache: dict[str, dict] = {}
        for slug, tg_data in teams_games.items():
            team_name = tg_data["name"]
            for g in tg_data["games"]:
                gid = g.get("game_id", "")
                if not gid:
                    continue
                if gid not in game_json_cache:
                    gpath = base / "data" / f"{gid}.json"
                    if gpath.exists():
                        with open(gpath) as _f:
                            game_json_cache[gid] = json.load(_f)
                gdata = game_json_cache.get(gid)
                if not gdata:
                    continue
                tno = None
                if gdata.get("team1", {}).get("name") == team_name:
                    tno = "1"
                elif gdata.get("team2", {}).get("name") == team_name:
                    tno = "2"
                if not tno:
                    continue
                tss = (gdata.get("teamShotStats") or {}).get(tno, {})
                q = tss.get("qualifiers", {})
                g["fromturnover_pts"] = q.get("fromturnover", {}).get("pts", 0)
                g["paint_pts"] = q.get("paint", {}).get("pts", 0)
                g["secondchance_pts"] = q.get("secondchance", {}).get("pts", 0)
                g["fastbreak_pts"] = q.get("fastbreak", {}).get("pts", 0)
                g["bench_pts"] = tss.get("benchPts", 0)
                g["biggest_lead"] = tss.get("biggestLead", 0)
                g["biggest_run"] = tss.get("biggestRun", 0)
                g["isHome"] = (tno == "1")

        template = env.get_template("stats_teams.html")
        html = template.render(
            season=season,
            teams_json=json.dumps(team_stats, ensure_ascii=False),
            teams_games_json=json.dumps(teams_games, ensure_ascii=False),
            assist_pairs_json=json.dumps(assist_pairs, ensure_ascii=False),
            nav_base="../../", nav_active="stats-teams", nav_season=season,
        )
        with open(out_dir / "teams.html", "w") as f:
            f.write(html)

        count += 1

    print(f"  Generated: stats pages for {count} season(s)")


def generate_leaderboard_pages(docs_path: Path | None = None):
    """Generate player and team leaderboard pages from season_log.json."""
    from .stats import load_season_log, compute_player_season_stats, compute_team_season_stats

    base = docs_path or DOCS_DIR
    log = load_season_log(base)

    if not log["players"] and not log["teams"]:
        print("  No season log data for leaderboards.")
        return

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    seasons: dict[str, dict] = {}
    for slug, pdata in log["players"].items():
        games = pdata.get("games", [])
        if not games:
            continue
        season = _date_to_season(games[0]["date"])
        if season not in seasons:
            seasons[season] = {"players": {}, "teams": {}}
        seasons[season]["players"][slug] = pdata

    for slug, tdata in log["teams"].items():
        games = tdata.get("games", [])
        if not games:
            continue
        season = _date_to_season(games[0]["date"])
        if season not in seasons:
            seasons[season] = {"players": {}, "teams": {}}
        seasons[season]["teams"][slug] = tdata

    count = 0
    for season, sdata in seasons.items():
        out_dir = base / "leaderboard" / season
        out_dir.mkdir(parents=True, exist_ok=True)

        player_stats = [
            compute_player_season_stats(slug, pdata)
            for slug, pdata in sdata["players"].items()
        ]
        player_stats = [p for p in player_stats if p.get("gp", 0) > 0]

        # Load player on/off ratings if available
        ratings_file = base / "data" / f"player_ratings_{season}.json"
        player_ratings = []
        if ratings_file.exists():
            with open(ratings_file) as f:
                player_ratings = json.load(f)

        template = env.get_template("leaderboard_players.html")
        html = template.render(
            season=season,
            players_json=json.dumps(player_stats, ensure_ascii=False),
            game_meta_json=json.dumps(log["game_meta"], ensure_ascii=False),
            ratings_json=json.dumps(player_ratings, ensure_ascii=False),
            nav_base="../../", nav_active="leaderboard-players", nav_season=season,
        )
        with open(out_dir / "players.html", "w") as f:
            f.write(html)

        team_stats = [
            compute_team_season_stats(slug, tdata)
            for slug, tdata in sdata["teams"].items()
        ]
        team_stats = [t for t in team_stats if t.get("gp", 0) > 0]

        template = env.get_template("leaderboard_teams.html")
        html = template.render(
            season=season,
            teams_json=json.dumps(team_stats, ensure_ascii=False),
            nav_base="../../", nav_active="leaderboard-teams", nav_season=season,
        )
        with open(out_dir / "teams.html", "w") as f:
            f.write(html)

        count += 1

    print(f"  Generated: leaderboard pages for {count} season(s)")


def generate_top_games_page(all_games_data: list[dict], docs_path: Path | None = None):
    """Generate top game records page."""
    base = docs_path or DOCS_DIR
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    if not all_games_data:
        print("  No game data for top games page.")
        return

    season = _date_to_season(all_games_data[0].get("date", ""))

    # ── Compute per-game metrics ──────────────────────────────────────────────
    def _team_totals(game, tno):
        players = [p for p in game["players"].get(str(tno), [])
                   if not p.get("isDNP", False)]
        keys = ["pf", "fta", "ftm", "fg3a", "fg3m"]
        return {k: sum(p.get("gameStats", {}).get(k, 0) for p in players) for k in keys}

    def _comeback(game):
        pm = game.get("teamPlusMinus", {}).get("1", [])
        if not pm:
            return 0
        s, mn, mx = 0, 0, 0
        for v in pm:
            s += v
            mn = min(mn, s)
            mx = max(mx, s)
        s1, s2 = game["team1"]["score"], game["team2"]["score"]
        if s1 > s2:
            return max(0, -mn)   # team1 won: how far behind were they?
        elif s2 > s1:
            return max(0, mx)    # team2 won: how far ahead was team1 at max?
        return 0

    rows = []
    for g in all_games_data:
        gid = g["gameId"]
        t1, s1 = g["team1"]["name"], g["team1"]["score"]
        t2, s2 = g["team2"]["name"], g["team2"]["score"]
        tt1, tt2 = _team_totals(g, 1), _team_totals(g, 2)

        ft_pct1 = round(tt1["ftm"] / tt1["fta"] * 100, 1) if tt1["fta"] >= 5 else None
        ft_pct2 = round(tt2["ftm"] / tt2["fta"] * 100, 1) if tt2["fta"] >= 5 else None
        ft_pct_both = (round((tt1["ftm"] + tt2["ftm"]) / (tt1["fta"] + tt2["fta"]) * 100, 1)
                       if (tt1["fta"] + tt2["fta"]) >= 10 else None)
        fg3_pct1 = round(tt1["fg3m"] / tt1["fg3a"] * 100, 1) if tt1["fg3a"] >= 5 else None
        fg3_pct2 = round(tt2["fg3m"] / tt2["fg3a"] * 100, 1) if tt2["fg3a"] >= 5 else None
        fg3_pct_both = (round((tt1["fg3m"] + tt2["fg3m"]) / (tt1["fg3a"] + tt2["fg3a"]) * 100, 1)
                        if (tt1["fg3a"] + tt2["fg3a"]) >= 10 else None)

        rows.append({
            "gid": gid, "date": g.get("date", ""),
            "t1": t1, "s1": s1, "t2": t2, "s2": s2,
            # score
            "diff": abs(s1 - s2), "combined": s1 + s2, "comeback": _comeback(g),
            # fouls
            "pf1": tt1["pf"], "pf2": tt2["pf"], "pf_both": tt1["pf"] + tt2["pf"],
            # FT
            "fta1": tt1["fta"], "fta2": tt2["fta"], "fta_both": tt1["fta"] + tt2["fta"],
            "ftm1": tt1["ftm"], "ftm2": tt2["ftm"], "ftm_both": tt1["ftm"] + tt2["ftm"],
            "ftx1": tt1["fta"] - tt1["ftm"], "ftx2": tt2["fta"] - tt2["ftm"],
            "ftx_both": (tt1["fta"] - tt1["ftm"]) + (tt2["fta"] - tt2["ftm"]),
            "ft_pct1": ft_pct1, "ft_pct2": ft_pct2, "ft_pct_both": ft_pct_both,
            # FT raw for note
            "ftm1_raw": tt1["ftm"], "fta1_raw": tt1["fta"],
            "ftm2_raw": tt2["ftm"], "fta2_raw": tt2["fta"],
            # 3P
            "fg3a1": tt1["fg3a"], "fg3a2": tt2["fg3a"], "fg3a_both": tt1["fg3a"] + tt2["fg3a"],
            "fg3m1": tt1["fg3m"], "fg3m2": tt2["fg3m"], "fg3m_both": tt1["fg3m"] + tt2["fg3m"],
            "fg3x1": tt1["fg3a"] - tt1["fg3m"], "fg3x2": tt2["fg3a"] - tt2["fg3m"],
            "fg3x_both": (tt1["fg3a"] - tt1["fg3m"]) + (tt2["fg3a"] - tt2["fg3m"]),
            "fg3_pct1": fg3_pct1, "fg3_pct2": fg3_pct2, "fg3_pct_both": fg3_pct_both,
            "fg3m1_raw": tt1["fg3m"], "fg3a1_raw": tt1["fg3a"],
            "fg3m2_raw": tt2["fg3m"], "fg3a2_raw": tt2["fg3a"],
        })

    # ── Record finders ────────────────────────────────────────────────────────
    def _ginfo(r):
        return {"gid": r["gid"], "date": r["date"],
                "t1": r["t1"], "s1": r["s1"], "t2": r["t2"], "s2": r["s2"]}

    def _max_both(key, label, unit="", note_fn=None):
        r = max(rows, key=lambda x: x[key])
        return {"label": label, "value": r[key], "unit": unit,
                "note": note_fn(r) if note_fn else "", **_ginfo(r)}

    def _min_both(key, label, unit="", note_fn=None):
        r = min(rows, key=lambda x: x[key])
        return {"label": label, "value": r[key], "unit": unit,
                "note": note_fn(r) if note_fn else "", **_ginfo(r)}

    def _max_one(k1, k2, label, unit="", note_fn=None):
        best_val, best_r, best_which = -1, None, 1
        for r in rows:
            if r[k1] > best_val:
                best_val, best_r, best_which = r[k1], r, 1
            if r[k2] > best_val:
                best_val, best_r, best_which = r[k2], r, 2
        note = note_fn(best_r, best_which) if note_fn else (best_r["t1"] if best_which == 1 else best_r["t2"])
        return {"label": label, "value": best_val, "unit": unit, "note": note, **_ginfo(best_r)}

    def _max_one_pct(pk1, pk2, mk1, ak1, mk2, ak2, label, min_att=5):
        cands = [(r, 1, r[pk1]) for r in rows if r[pk1] is not None] + \
                [(r, 2, r[pk2]) for r in rows if r[pk2] is not None]
        if not cands:
            return None
        best_r, best_which, best_val = max(cands, key=lambda x: x[2])
        m, a = (best_r[mk1], best_r[ak1]) if best_which == 1 else (best_r[mk2], best_r[ak2])
        team = best_r["t1"] if best_which == 1 else best_r["t2"]
        return {"label": label, "value": f"{best_val}%", "unit": "",
                "note": f"{team}: {m}/{a}", **_ginfo(best_r)}

    def _min_one_pct(pk1, pk2, mk1, ak1, mk2, ak2, label):
        cands = [(r, 1, r[pk1]) for r in rows if r[pk1] is not None] + \
                [(r, 2, r[pk2]) for r in rows if r[pk2] is not None]
        if not cands:
            return None
        best_r, best_which, best_val = min(cands, key=lambda x: x[2])
        m, a = (best_r[mk1], best_r[ak1]) if best_which == 1 else (best_r[mk2], best_r[ak2])
        team = best_r["t1"] if best_which == 1 else best_r["t2"]
        return {"label": label, "value": f"{best_val}%", "unit": "",
                "note": f"{team}: {m}/{a}", **_ginfo(best_r)}

    def _max_both_pct(pk, mk, ak, label):
        cands = [r for r in rows if r[pk] is not None]
        if not cands:
            return None
        r = max(cands, key=lambda x: x[pk])
        m1, a1 = r[mk.replace("_both", "1")], r[ak.replace("_both", "1")]
        m2, a2 = r[mk.replace("_both", "2")], r[ak.replace("_both", "2")]
        return {"label": label, "value": f"{r[pk]}%", "unit": "",
                "note": f"{m1+m2}/{a1+a2}", **_ginfo(r)}

    def _min_both_pct(pk, mk, ak, label):
        cands = [r for r in rows if r[pk] is not None]
        if not cands:
            return None
        r = min(cands, key=lambda x: x[pk])
        m1, a1 = r[mk.replace("_both", "1")], r[ak.replace("_both", "1")]
        m2, a2 = r[mk.replace("_both", "2")], r[ak.replace("_both", "2")]
        return {"label": label, "value": f"{r[pk]}%", "unit": "",
                "note": f"{m1+m2}/{a1+a2}", **_ginfo(r)}

    def _ft_note(r, which):
        if which == 1:
            return f"{r['t1']}: {r['ftm1_raw']}/{r['fta1_raw']}"
        return f"{r['t2']}: {r['ftm2_raw']}/{r['fta2_raw']}"

    def _ftx_note(r, which):
        if which == 1:
            return f"{r['t1']}: {r['fta1_raw'] - r['ftm1_raw']}/{r['fta1_raw']}"
        return f"{r['t2']}: {r['fta2_raw'] - r['ftm2_raw']}/{r['fta2_raw']}"

    def _3p_note(r, which):
        if which == 1:
            return f"{r['t1']}: {r['fg3m1_raw']}/{r['fg3a1_raw']}"
        return f"{r['t2']}: {r['fg3m2_raw']}/{r['fg3a2_raw']}"

    def _3px_note(r, which):
        if which == 1:
            return f"{r['t1']}: {r['fg3a1_raw'] - r['fg3m1_raw']}/{r['fg3a1_raw']}"
        return f"{r['t2']}: {r['fg3a2_raw'] - r['fg3m2_raw']}/{r['fg3a2_raw']}"

    def _pf_note(r, which):
        return r["t1"] if which == 1 else r["t2"]

    # ── Build sections ────────────────────────────────────────────────────────
    def _filter_none(lst):
        return [x for x in lst if x is not None]

    def _comeback_record():
        cands = [r for r in rows if r["comeback"] > 0]
        if not cands:
            return None
        r = max(cands, key=lambda x: x["comeback"])
        team = r["t1"] if r["s1"] > r["s2"] else r["t2"]
        return {"label": "Největší comeback", "value": r["comeback"], "unit": "bodů",
                "note": team, **_ginfo(r)}

    sections = [
        {
            "title": "Skóre & výsledky",
            "records": _filter_none([
                _max_both("diff",     "Nejvyšší rozdíl skóre",                "bodů"),
                _max_both("combined", "Nejvíce bodů v zápase celkem",         "bodů"),
                _min_both("combined", "Nejméně bodů v zápase celkem",         "bodů"),
                _comeback_record(),
            ]),
        },
        {
            "title": "Fauly & trestné hody",
            "records": _filter_none([
                _max_one("pf1",  "pf2",  "Nejvíce faulů – jeden tým",  "faulů", _pf_note),
                _max_both("pf_both",  "Nejvíce faulů – oba týmy",      "faulů"),
                _max_one("fta1", "fta2", "Nejvíce pokusů TH – jeden tým", "TH", _ft_note),
                _max_both("fta_both", "Nejvíce pokusů TH – oba týmy", "TH",
                          note_fn=lambda r: f"{r['ftm_both']}/{r['fta_both']}"),
                _max_one("ftm1", "ftm2", "Nejvíce proměněných TH – jeden tým", "TH", _ft_note),
                _max_both("ftm_both", "Nejvíce proměněných TH – oba týmy", "TH",
                          note_fn=lambda r: f"{r['ftm_both']}/{r['fta_both']}"),
                _max_one("ftx1", "ftx2", "Nejvíce neproměněných TH – jeden tým", "TH", _ftx_note),
                _max_both("ftx_both", "Nejvíce neproměněných TH – oba týmy", "TH",
                          note_fn=lambda r: f"{r['ftx_both']}/{r['fta_both']}"),
                _max_one_pct("ft_pct1", "ft_pct2", "ftm1_raw", "fta1_raw", "ftm2_raw", "fta2_raw",
                             "Nejlepší % TH – jeden tým"),
                _min_one_pct("ft_pct1", "ft_pct2", "ftm1_raw", "fta1_raw", "ftm2_raw", "fta2_raw",
                             "Nejhorší % TH – jeden tým"),
            ]),
        },
        {
            "title": "Trojky",
            "records": _filter_none([
                _max_one("fg3a1", "fg3a2", "Nejvíce pokusů o trojku – jeden tým", "3PA", _3p_note),
                _max_both("fg3a_both", "Nejvíce pokusů o trojku – oba týmy",       "3PA"),
                _max_one("fg3m1", "fg3m2", "Nejvíce proměněných trojek – jeden tým", "3PM", _3p_note),
                _max_both("fg3m_both", "Nejvíce proměněných trojek – oba týmy",    "3PM"),
                _max_one("fg3x1", "fg3x2", "Nejvíce neproměněných trojek – jeden tým", "3Px", _3px_note),
                _max_both("fg3x_both", "Nejvíce neproměněných trojek – oba týmy",  "3Px"),
                _max_one_pct("fg3_pct1", "fg3_pct2", "fg3m1_raw", "fg3a1_raw", "fg3m2_raw", "fg3a2_raw",
                             "Nejlepší % trojek – jeden tým"),
                _max_both_pct("fg3_pct_both", "fg3m_both", "fg3a_both",
                              "Nejlepší % trojek – oba týmy"),
                _min_one_pct("fg3_pct1", "fg3_pct2", "fg3m1_raw", "fg3a1_raw", "fg3m2_raw", "fg3a2_raw",
                             "Nejhorší % trojek – jeden tým"),
                _min_both_pct("fg3_pct_both", "fg3m_both", "fg3a_both",
                              "Nejhorší % trojek – oba týmy"),
            ]),
        },
    ]

    # ── Top 20 longest stints ─────────────────────────────────────────────────
    all_stints = []
    for g in all_games_data:
        gid = g["gameId"]
        date = g.get("date", "")
        t1, s1 = g["team1"]["name"], g["team1"]["score"]
        t2, s2 = g["team2"]["name"], g["team2"]["score"]
        for tno_str in ["1", "2"]:
            team_name = g[f"team{tno_str}"]["name"]
            opp_name = g["team2"]["name"] if tno_str == "1" else g["team1"]["name"]
            for player in g["players"].get(tno_str, []):
                if player.get("isDNP"):
                    continue
                first_name = player.get("firstName", "")
                family_name = player.get("familyName", "")
                short_name = player.get("name", "")
                if not first_name or not family_name:
                    continue
                player_slug = (f"{_slugify(team_name)}-"
                               f"{_slugify(first_name)}-"
                               f"{_slugify(family_name)}")
                for start, end, length in _compute_stints(player):
                    all_stints.append({
                        "length": length,
                        "start": start,
                        "end": end,
                        "player_name": short_name,
                        "player_slug": player_slug,
                        "player_season": season,
                        "team": team_name,
                        "gid": gid,
                        "date": date,
                        "t1": t1, "s1": s1, "t2": t2, "s2": s2,
                    })
    all_stints.sort(key=lambda s: (-s["length"], s["date"]))
    top_stints = all_stints[:20]

    # ── Render ────────────────────────────────────────────────────────────────
    out_dir = base / "stats" / season
    out_dir.mkdir(parents=True, exist_ok=True)
    template = env.get_template("top_games.html")
    html = template.render(
        season=season,
        sections=sections,
        top_stints=top_stints,
        nav_base="../../", nav_active="top-games", nav_season=season,
    )
    with open(out_dir / "top_games.html", "w") as f:
        f.write(html)
    print(f"  Generated: stats/{season}/top_games.html")


_MILESTONE_CATEGORIES = [
    {"key": "pts",             "label": "Body (PTS)",             "unit": "bodů",      "scale": 1,      "threshold": 1.5},
    {"key": "ast",             "label": "Asistence (AST)",        "unit": "asistencí", "scale": 1,      "threshold": 1.5},
    {"key": "ftm",             "label": "Trestné hody (FTM)",     "unit": "TH",        "scale": 1,      "threshold": 1.5},
    {"key": "fgm",             "label": "Střely proměněné (FGM)", "unit": "střel",     "scale": 1,      "threshold": 1.5},
    {"key": "fg3m",            "label": "Trojky (3PM)",           "unit": "trojek",    "scale": 1,      "threshold": 1.5},
    {"key": "minutes_seconds", "label": "Minuty",                 "unit": "min",       "scale": 1 / 60, "threshold": 1.2},
]


def generate_milestones_page(docs_path: Path | None = None):
    """Generate expected milestones page."""
    base = docs_path or DOCS_DIR
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    log_path = base / "data" / "season_log.json"
    if not log_path.exists():
        print("  No season_log.json found for milestones page.")
        return

    with open(log_path) as f:
        log = json.load(f)

    players = log.get("players", {})
    all_dates = [g["date"] for p in players.values()
                 for g in p.get("games", []) if g.get("date")]
    season = _date_to_season(max(all_dates)) if all_dates else "2025-26"

    from .stats import _make_player_slug

    def _next_milestone(value: float, step: int = 100) -> int:
        return (int(value // step) + 1) * step

    def _fmt(value: float, scale: float) -> str:
        if scale != 1:
            return f"{value:.1f}"
        return str(int(round(value)))

    sections = []
    for cat in _MILESTONE_CATEGORIES:
        key = cat["key"]
        scale = cat["scale"]
        unit = cat["unit"]
        threshold = cat["threshold"]
        entries = []

        for pdata in players.values():
            played = [g for g in pdata.get("games", []) if not g.get("isDNP", False)]
            gp = len(played)
            if gp == 0:
                continue

            total_raw = sum(g.get(key, 0) for g in played)
            total = total_raw * scale
            avg = total / gp
            if avg == 0:
                continue

            milestone = _next_milestone(total)
            remaining = milestone - total

            if remaining <= avg * threshold:
                slug = _make_player_slug(
                    pdata["firstName"], pdata["familyName"], pdata["team"])
                entries.append({
                    "firstName": pdata["firstName"],
                    "familyName": pdata["familyName"],
                    "team": pdata["team"],
                    "slug": slug,
                    "current": _fmt(total, scale),
                    "milestone": milestone,
                    "remaining": _fmt(remaining, scale),
                    "avg": f"{avg:.1f}",
                    "games_to_go": f"{remaining / avg:.1f}",
                })

        if not entries:
            continue

        # For minutes: keep only players above 50% of the highest milestone in section
        if key == "minutes_seconds":
            max_milestone = max(e["milestone"] for e in entries)
            entries = [e for e in entries if float(e["current"]) >= max_milestone * 0.5]

        if not entries:
            continue

        entries.sort(key=lambda e: e["milestone"], reverse=True)
        sections.append({"title": cat["label"], "unit": unit, "entries": entries})

    out_dir = base / "stats" / season
    out_dir.mkdir(parents=True, exist_ok=True)
    template = env.get_template("milestones.html")
    html = template.render(
        season=season,
        sections=sections,
        nav_base="../../", nav_active="milestones", nav_season=season,
    )
    with open(out_dir / "milestones.html", "w") as f:
        f.write(html)
    print(f"  Generated: stats/{season}/milestones.html")


_MIN_MINUTES: dict[int, int] = {2: 20, 3: 15, 4: 12, 5: 10}


def generate_top_performances_page(docs_path: Path | None = None):
    """Generate league-wide TOP5 performances per stat category + triple doubles."""
    base = docs_path or DOCS_DIR
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    log_path = base / "data" / "season_log.json"
    if not log_path.exists():
        print("  No season_log.json found for top performances page.")
        return

    with open(log_path) as f:
        log = json.load(f)

    players = log.get("players", {})
    all_dates = [g["date"] for p in players.values() for g in p.get("games", []) if g.get("date")]
    if not all_dates:
        return
    season = _date_to_season(max(all_dates))

    SIMPLE_KEYS = [
        "pts", "q1", "q2", "q3", "q4",
        "reb", "oreb", "dreb",
        "ast", "stl", "blk", "tov",
        "fgm", "fga", "fg2m", "fg2a", "fg3m", "fg3a", "ftm", "fta",
    ]
    ALL_KEYS = SIMPLE_KEYS + ["pm", "per", "fgpct", "fg2pct", "fg3pct", "ftpct"]
    records: dict[str, list] = {k: [] for k in ALL_KEYS}
    triple_doubles: list[dict] = []

    for slug, pdata in players.items():
        first = pdata.get("firstName", "")
        family = pdata.get("familyName", "")
        player_name = f"{first} {family}".strip() or slug
        cur_team = pdata.get("team", "")

        for g in pdata.get("games", []):
            if g.get("isDNP", False):
                continue

            gid = g.get("game_id", "")
            team = g.get("team", cur_team)
            base_info = {
                "player_name": player_name,
                "player_slug": slug,
                "player_season": season,
                "team": team,
                "game_id": gid,
                "date": g.get("date", ""),
                "opponent": g.get("opponent", ""),
            }

            for k in SIMPLE_KEYS:
                v = g.get(k) or 0
                records[k].append({**base_info, "value": v, "display": str(v)})

            pm = g.get("plus_minus") or 0
            records["pm"].append({**base_info, "value": pm,
                "display": ("+" + str(pm)) if pm > 0 else str(pm)})

            per_v = (
                (g.get("pts") or 0) + (g.get("reb") or 0) + (g.get("ast") or 0) +
                (g.get("stl") or 0) + (g.get("blk") or 0) -
                ((g.get("fga") or 0) - (g.get("fgm") or 0)) -
                ((g.get("fta") or 0) - (g.get("ftm") or 0)) -
                (g.get("tov") or 0)
            )
            records["per"].append({**base_info, "value": per_v, "display": str(per_v)})

            fga, fgm = (g.get("fga") or 0), (g.get("fgm") or 0)
            if fga >= 10:
                v = fgm / fga
                records["fgpct"].append({**base_info, "value": v,
                    "display": f"{v*100:.1f}% ({fgm}/{fga})"})

            fg2a, fg2m = (g.get("fg2a") or 0), (g.get("fg2m") or 0)
            if fg2a >= 10:
                v = fg2m / fg2a
                records["fg2pct"].append({**base_info, "value": v,
                    "display": f"{v*100:.1f}% ({fg2m}/{fg2a})"})

            fg3a, fg3m = (g.get("fg3a") or 0), (g.get("fg3m") or 0)
            if fg3a >= 5:
                v = fg3m / fg3a
                records["fg3pct"].append({**base_info, "value": v,
                    "display": f"{v*100:.1f}% ({fg3m}/{fg3a})"})

            fta, ftm = (g.get("fta") or 0), (g.get("ftm") or 0)
            if fta >= 5:
                v = ftm / fta
                records["ftpct"].append({**base_info, "value": v,
                    "display": f"{v*100:.1f}% ({ftm}/{fta})"})

            # Triple double: ≥10 in any 3 of {pts, reb, ast, stl, blk}
            td_vals = {k: (g.get(k) or 0) for k in ["pts", "reb", "ast", "stl", "blk"]}
            if sum(1 for v in td_vals.values() if v >= 10) >= 3:
                shown = {k: v for k, v in td_vals.items() if v >= 9}
                triple_doubles.append({**base_info, "td_stats": shown})

    # Sort and keep TOP5
    top5: dict[str, list] = {
        k: sorted(records[k], key=lambda x: x["value"], reverse=True)[:5]
        for k in ALL_KEYS
    }

    # Load game JSONs for score / isHome enrichment (only games referenced in TOP5 + TDs)
    game_cache: dict[str, dict] = {}
    needed_gids = {e["game_id"] for entries in top5.values() for e in entries} | \
                  {td["game_id"] for td in triple_doubles}
    for gid in needed_gids:
        gpath = base / "data" / f"{gid}.json"
        if gpath.exists():
            with open(gpath) as f:
                game_cache[gid] = json.load(f)

    def _enrich(entry: dict) -> dict:
        gid = entry.get("game_id", "")
        gdata = game_cache.get(gid, {})
        t1name = gdata.get("team1", {}).get("name", "")
        s1 = gdata.get("team1", {}).get("score", "")
        s2 = gdata.get("team2", {}).get("score", "")
        score = f"{s1}:{s2}" if s1 != "" and s2 != "" else ""
        is_home = (entry.get("team", "") == t1name) if t1name else True
        dp = entry.get("date", "").split("-")
        date_fmt = f"{dp[2]}.{dp[1]}.{dp[0]}" if len(dp) == 3 else entry.get("date", "")
        return {**entry, "score": score, "is_home": is_home,
                "loc": "vs." if is_home else "@", "date_fmt": date_fmt}

    SECTION_DEFS = [
        ("Skórování", [
            ("Body", "pts"), ("PER", "per"),
            ("1. čtvrtina", "q1"), ("2. čtvrtina", "q2"),
            ("3. čtvrtina", "q3"), ("4. čtvrtina", "q4"), ("+/−", "pm"),
        ]),
        ("Doskoky", [
            ("Doskoky celkem", "reb"), ("Útočné doskoky", "oreb"), ("Obranné doskoky", "dreb"),
        ]),
        ("Ostatní statistiky", [
            ("Asistence", "ast"), ("Zisky", "stl"), ("Bloky", "blk"), ("Ztráty", "tov"),
        ]),
        ("Střelba", [
            ("FGM", "fgm"), ("FGA", "fga"), ("2PM", "fg2m"), ("2PA", "fg2a"),
            ("3PM", "fg3m"), ("3PA", "fg3a"), ("FTM", "ftm"), ("FTA", "fta"),
        ]),
        ("Úspěšnost střelby", [
            ("FG% (min 10)", "fgpct"), ("2P% (min 10)", "fg2pct"),
            ("3P% (min 5)", "fg3pct"), ("FT% (min 5)", "ftpct"),
        ]),
    ]

    sections_data = []
    for title, cats in SECTION_DEFS:
        cats_data = [{"label": label, "key": key,
                      "entries": [_enrich(e) for e in top5[key]]}
                     for label, key in cats]
        sections_data.append({"title": title, "categories": cats_data})

    _TD_LABELS = {"pts": "Pts", "reb": "Reb", "ast": "Ast", "stl": "Stl", "blk": "Blk"}
    _TD_ORDER = list(_TD_LABELS.keys())
    td_enriched = []
    for td in sorted(triple_doubles, key=lambda x: x["date"]):
        e = _enrich(td)
        stats_parts = [f"{_TD_LABELS[k]} {e['td_stats'][k]}"
                       for k in _TD_ORDER if k in e.get("td_stats", {})]
        e["stats_display"] = ", ".join(stats_parts)
        td_enriched.append(e)

    template = env.get_template("top_performances.html")
    out_dir = base / "stats" / season
    out_dir.mkdir(parents=True, exist_ok=True)
    html = template.render(
        season=season,
        sections=sections_data,
        triple_doubles=td_enriched,
        nav_base="../../", nav_active="top-performances", nav_season=season,
    )
    with open(out_dir / "top_performances.html", "w") as f:
        f.write(html)
    print(f"  Generated: stats/{season}/top_performances.html")


def generate_ratings_pages(all_games_data: list[dict], docs_path: Path | None = None):
    """Generate ratings.html and per-team ratings pages."""
    base = docs_path or DOCS_DIR
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    if not all_games_data:
        print("  No game data for ratings pages.")
        return

    # Use last game's date to determine season
    dates = [g.get("date", "") for g in all_games_data if g.get("date")]
    season = _date_to_season(dates[-1]) if dates else "2025-26"

    print("  Computing lineup/on-off stats…")
    season_onoff = compute_season_onoff(all_games_data)
    data = aggregate_season_lineups(all_games_data, season_onoff)

    teams_sorted = sorted(data.values(), key=lambda t: -t["net_rtg"])

    # League top/bottom 5 per combo size
    league_combos: dict[int, dict] = {}
    for size in [2, 3, 4, 5]:
        all_combos = [
            {**combo, "team": td["name"], "team_slug": slug}
            for slug, td in data.items()
            for combo in td["lineups"].get(size, [])
            if combo["minutes"] >= _MIN_MINUTES[size]
        ]
        all_combos.sort(key=lambda c: -c["stabilized_net"])
        worst = sorted(all_combos, key=lambda c: c["stabilized_net"])
        league_combos[size] = {
            "best": all_combos[:5],
            "worst": worst[:5],
        }

    # Build short_name → player_slug lookup
    _player_last_team: dict[str, str] = {}
    _player_names: dict[str, tuple] = {}
    for game_json in all_games_data:
        for tno in ["1", "2"]:
            team_name = game_json.get(f"team{tno}", {}).get("name", "")
            if not team_name:
                continue
            for player in game_json.get("players", {}).get(tno, []):
                first = player.get("firstName", "")
                family = player.get("familyName", "")
                short = player.get("name", "")
                if not first or not family or not short:
                    continue
                pk = f"{first}_{family}"
                _player_names[pk] = (short, first, family)
                _player_last_team[pk] = team_name
    _short_to_slug: dict[str, str] = {}
    for pk, (short, first, family) in _player_names.items():
        last_team = _player_last_team[pk]
        _short_to_slug[short] = f"{_slugify(last_team)}-{_slugify(first)}-{_slugify(family)}"

    # Build per-team player on/off for "Přínos hráčů" section
    team_players_onoff: dict[str, list] = {}
    for slug, td in data.items():
        total_minutes = td["total_minutes"]
        prefix = f"{slug}|"
        players = []
        for key, od in season_onoff.items():
            if not key.startswith(prefix):
                continue
            player_name = key[len(prefix):]
            on = od["on"]
            off = od["off"]
            if on["poss"] <= 0 or on["opp_poss"] <= 0:
                continue
            on_ortg = round(on["pts"] / on["poss"] * 100, 1)
            on_drtg = round(on["opp_pts"] / on["opp_poss"] * 100, 1)
            on_net = round(on_ortg - on_drtg, 1)
            on_minutes = on["minutes"]
            on_pct = round(on_minutes / total_minutes * 100) if total_minutes > 0 else 0
            has_off = off["poss"] > 0 and off["opp_poss"] > 0
            off_ortg = round(off["pts"] / off["poss"] * 100, 1) if has_off else None
            off_drtg = round(off["opp_pts"] / off["opp_poss"] * 100, 1) if has_off else None
            off_net = round(off_ortg - off_drtg, 1) if has_off else None
            off_minutes = off["minutes"] if has_off else 0
            delta_net = round(on_net - off_net, 1) if has_off else None
            players.append({
                "name": player_name,
                "slug": _short_to_slug.get(player_name, ""),
                "on_minutes": on_minutes,
                "on_pct": on_pct,
                "on_ortg": on_ortg,
                "on_drtg": on_drtg,
                "on_net": on_net,
                "off_minutes": off_minutes,
                "off_ortg": off_ortg,
                "off_drtg": off_drtg,
                "off_net": off_net,
                "has_off": has_off,
                "delta_net": delta_net,
            })
        players.sort(key=lambda p: -(p["delta_net"] if p["delta_net"] is not None else float("-inf")))
        team_players_onoff[slug] = players

    # Render main ratings.html
    out_dir = base / "stats" / season
    out_dir.mkdir(parents=True, exist_ok=True)

    template = env.get_template("ratings.html")
    html = template.render(
        season=season,
        teams=teams_sorted,
        league_combos=league_combos,
        sizes=[2, 3, 4, 5],
        size_labels={2: "Duo", 3: "Trio", 4: "Čtveřice", 5: "Pětka"},
        min_minutes=_MIN_MINUTES,
        nav_base="../../", nav_active="ratings", nav_season=season,
    )
    with open(out_dir / "ratings.html", "w") as f:
        f.write(html)
    print(f"  Generated: stats/{season}/ratings.html")

    # Render per-team ratings pages
    ratings_dir = out_dir / "ratings"
    ratings_dir.mkdir(exist_ok=True)

    template_team = env.get_template("ratings_team.html")
    for slug, td in data.items():
        # Filter combos per size by minimum minutes
        filtered_lineups: dict[int, list] = {}
        for size in [2, 3, 4, 5]:
            filtered_lineups[size] = sorted(
                [c for c in td["lineups"].get(size, []) if c["minutes"] >= _MIN_MINUTES[size]],
                key=lambda c: -c["stabilized_net"],
            )

        html = template_team.render(
            season=season,
            team=td,
            filtered_lineups=filtered_lineups,
            players_onoff=team_players_onoff.get(slug, []),
            sizes=[2, 3, 4, 5],
            size_labels={2: "Duo", 3: "Trio", 4: "Čtveřice", 5: "Pětka"},
            min_minutes=_MIN_MINUTES,
            nav_base="../../../", nav_active="ratings", nav_season=season,
        )
        html_path = ratings_dir / f"{slug}.html"
        with open(html_path, "w") as f:
            f.write(html)

    print(f"  Generated: stats/{season}/ratings/{{}}.html for {len(data)} teams")


def generate_assist_pairs_data(all_games_data: list[dict], docs_path: Path | None = None):
    """Aggregate passer→scorer assist pairs across all games, save per-season JSON.

    Output: docs/data/assist_pairs_{season}.json with keys:
      season, by_team (dict team→sorted list), league (top 20, min 20 ast),
      best_passers (top 20, min 10 ast), best_scorers (top 20, min 10 ast).
    """
    base = docs_path or DOCS_DIR

    # {season: {(team, passer_key, scorer_key): aggregated}}
    season_pairs: dict[str, dict] = {}
    # last seen team for each player key (for slug construction)
    player_last_team: dict[str, str] = {}

    sorted_games = sorted(all_games_data, key=lambda g: g.get("date", ""))

    for game_json in sorted_games:
        date = game_json.get("date", "")
        season = _date_to_season(date)
        if season not in season_pairs:
            season_pairs[season] = {}

        # Build per-team lookups
        name_lookup: dict[tuple, tuple] = {}   # (tno, shirt) -> (first, family)
        stints_lookup: dict[tuple, list] = {}  # (tno, shirt) -> rawStints

        for tno_str in ["1", "2"]:
            tno = int(tno_str)
            team_name = game_json[f"team{tno_str}"]["name"]
            for player in game_json["players"][tno_str]:
                shirt = player["shirtNumber"]
                first = player.get("firstName", "")
                family = player.get("familyName", "")
                if not first or not family:
                    continue
                k = (tno, shirt)
                name_lookup[k] = (first, family)
                stints_lookup[k] = player.get("rawStints", [])
                player_last_team[f"{first}_{family}"] = team_name

        for pair in game_json.get("assistPairs", []):
            tno = pair["tno"]
            tno_str = str(tno)
            team_name = game_json[f"team{tno_str}"]["name"]
            pk = (tno, pair["passer_shirt"])
            sk = (tno, pair["scorer_shirt"])
            passer_names = name_lookup.get(pk)
            scorer_names = name_lookup.get(sk)
            if not passer_names or not scorer_names:
                continue
            passer_key = f"{passer_names[0]}_{passer_names[1]}"
            scorer_key = f"{scorer_names[0]}_{scorer_names[1]}"
            agg_key = (team_name, passer_key, scorer_key)

            if agg_key not in season_pairs[season]:
                season_pairs[season][agg_key] = {
                    "team": team_name,
                    "passer_first": passer_names[0], "passer_family": passer_names[1],
                    "scorer_first": scorer_names[0], "scorer_family": scorer_names[1],
                    "ast": 0, "ast2": 0, "ast3": 0, "pts": 0, "shared_seconds": 0.0,
                }
            agg = season_pairs[season][agg_key]
            for stat_k in ("ast", "ast2", "ast3", "pts"):
                agg[stat_k] += pair[stat_k]
            agg["shared_seconds"] += _compute_shared_seconds(
                stints_lookup.get(pk, []), stints_lookup.get(sk, []))

    for season, pairs_dict in season_pairs.items():
        result_by_team: dict[str, list] = {}

        for (team_name, passer_key, scorer_key), p in pairs_dict.items():
            shared_min = p["shared_seconds"] / 60.0
            p["shared_min"] = round(shared_min)
            if shared_min >= 5:
                p["ast_per36"] = round(p["ast"] / shared_min * 36, 1)
                p["pts_per36"] = round(p["pts"] / shared_min * 36, 1)
            else:
                p["ast_per36"] = None
                p["pts_per36"] = None

            # Slugs (based on last seen team)
            p_last = player_last_team.get(passer_key, team_name)
            s_last = player_last_team.get(scorer_key, team_name)
            p["passer_slug"] = (f"{_slugify(p_last)}-"
                                f"{_slugify(p['passer_first'])}-"
                                f"{_slugify(p['passer_family'])}")
            p["scorer_slug"] = (f"{_slugify(s_last)}-"
                                f"{_slugify(p['scorer_first'])}-"
                                f"{_slugify(p['scorer_family'])}")
            p["passer_season"] = season
            p["scorer_season"] = season
            p["passer_name"] = f"{p['passer_first']} {p['passer_family']}"
            p["scorer_name"] = f"{p['scorer_first']} {p['scorer_family']}"

            if team_name not in result_by_team:
                result_by_team[team_name] = []
            result_by_team[team_name].append(p)

        for team_name in result_by_team:
            result_by_team[team_name].sort(key=lambda x: -x["ast"])

        # League top 20 (min 20 assists)
        league_top20 = sorted(
            [p for p in pairs_dict.values() if p["ast"] >= 20],
            key=lambda x: -x["ast"])[:20]

        # Best passers (min 10 assisted FGs)
        passer_totals: dict[str, dict] = {}
        for (team_name, passer_key, _sk), p in pairs_dict.items():
            if passer_key not in passer_totals:
                passer_totals[passer_key] = {
                    "name": p["passer_name"], "slug": p["passer_slug"],
                    "season": season, "ast": 0, "ast2": 0, "ast3": 0, "pts": 0,
                    "_teams": {},
                }
            passer_totals[passer_key]["ast"] += p["ast"]
            passer_totals[passer_key]["ast2"] += p["ast2"]
            passer_totals[passer_key]["ast3"] += p["ast3"]
            passer_totals[passer_key]["pts"] += p["pts"]
            t = passer_totals[passer_key]["_teams"]
            t[team_name] = t.get(team_name, 0) + p["ast"]
        for v in passer_totals.values():
            v["team"] = max(v["_teams"], key=lambda t: v["_teams"][t]) if v["_teams"] else ""
            del v["_teams"]
        best_passers = sorted(
            [v for v in passer_totals.values() if v["ast"] >= 10],
            key=lambda x: -x["ast"])[:20]

        # Best scorers (min 10 assisted FGs)
        scorer_totals: dict[str, dict] = {}
        for (_tn, _pk, scorer_key), p in pairs_dict.items():
            if scorer_key not in scorer_totals:
                scorer_totals[scorer_key] = {
                    "name": p["scorer_name"], "slug": p["scorer_slug"],
                    "season": season, "ast": 0, "ast2": 0, "ast3": 0, "pts": 0,
                    "_teams": {},
                }
            scorer_totals[scorer_key]["ast"] += p["ast"]
            scorer_totals[scorer_key]["ast2"] += p["ast2"]
            scorer_totals[scorer_key]["ast3"] += p["ast3"]
            scorer_totals[scorer_key]["pts"] += p["pts"]
            t = scorer_totals[scorer_key]["_teams"]
            t[_tn] = t.get(_tn, 0) + p["ast"]
        for v in scorer_totals.values():
            v["team"] = max(v["_teams"], key=lambda t: v["_teams"][t]) if v["_teams"] else ""
            del v["_teams"]
        best_scorers = sorted(
            [v for v in scorer_totals.values() if v["ast"] >= 10],
            key=lambda x: -x["ast"])[:20]

        output = {
            "season": season,
            "by_team": result_by_team,
            "league": league_top20,
            "best_passers": best_passers,
            "best_scorers": best_scorers,
        }

        data_dir = base / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        with open(data_dir / f"assist_pairs_{season}.json", "w") as f:
            json.dump(output, f, ensure_ascii=False)
        print(f"  Assist pairs {season}: {sum(len(v) for v in result_by_team.values())} pairs "
              f"across {len(result_by_team)} teams")
