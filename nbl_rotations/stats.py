"""Season log management and aggregated statistics computation."""

import json
from pathlib import Path

SEASON_LOG_PATH = "data/season_log.json"

_PLAYER_STAT_KEYS = [
    "pts", "reb", "oreb", "dreb", "ast", "stl", "blk",
    "fgm", "fga", "fg2m", "fg2a", "fg3m", "fg3a",
    "ftm", "fta", "tov", "pf", "pfd", "technical",
]

_TEAM_STAT_KEYS = [
    "pts", "reb", "oreb", "dreb", "ast", "stl", "blk",
    "fgm", "fga", "fg2m", "fg2a", "fg3m", "fg3a",
    "ftm", "fta", "tov", "pf", "pfd",
]


def load_season_log(docs_path: Path) -> dict:
    """Load season_log.json, or return empty structure if it doesn't exist."""
    path = docs_path / SEASON_LOG_PATH
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"processed_games": [], "game_meta": {}, "players": {}, "teams": {}}


def save_season_log(log: dict, docs_path: Path) -> None:
    """Save season_log.json to docs/data/."""
    path = docs_path / SEASON_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(log, f)


def _sum_team_stats(players: list[dict]) -> dict:
    """Sum gameStats across all players for a team."""
    totals = {k: 0 for k in _TEAM_STAT_KEYS}
    for p in players:
        gs = p.get("gameStats", {})
        for k in _TEAM_STAT_KEYS:
            totals[k] += gs.get(k, 0)
    return totals


def update_season_log(log: dict, game_json: dict, game_id: str, game_meta: dict) -> None:
    """Add a game to the season log. Skips games already processed."""
    if game_id in log["processed_games"]:
        return

    log["processed_games"].append(game_id)
    log["game_meta"][game_id] = {
        "date": game_meta.get("date", ""),
        "team1": game_meta.get("team1", ""),
        "team2": game_meta.get("team2", ""),
        "score1": game_meta.get("score1", 0),
        "score2": game_meta.get("score2", 0),
    }

    players_data = game_json.get("players", {})
    team1_info = game_json.get("team1", {})
    team2_info = game_json.get("team2", {})
    date = game_meta.get("date", "")

    # Compute team totals (needed for Usage%)
    team_totals = {}
    for tno_str in ["1", "2"]:
        team_players = [p for p in players_data.get(tno_str, [])
                        if not p.get("isDNP", False)]
        team_totals[tno_str] = _sum_team_stats(team_players)

    # Player entries
    for tno_str in ["1", "2"]:
        team_info = team1_info if tno_str == "1" else team2_info
        opp_tno = "2" if tno_str == "1" else "1"
        opp_info = team1_info if opp_tno == "1" else team2_info
        team_name = team_info.get("name", "")
        tt = team_totals[tno_str]

        for player in players_data.get(tno_str, []):
            first_name = player.get("firstName", "")
            family_name = player.get("familyName", "")
            if not first_name or not family_name:
                continue

            slug = _make_player_slug(first_name, family_name, team_name)
            is_dnp = player.get("isDNP", False)
            gs = player.get("gameStats", {})

            if slug not in log["players"]:
                log["players"][slug] = {
                    "firstName": first_name,
                    "familyName": family_name,
                    "team": team_name,
                    "games": [],
                }
            else:
                # Update team (player may have changed teams)
                log["players"][slug]["team"] = team_name

            entry = {
                "game_id": game_id,
                "date": date,
                "opponent": opp_info.get("name", ""),
                "team": team_name,
                "isDNP": is_dnp,
                "minutes_seconds": player.get("totalSeconds", 0),
                "plus_minus": player.get("totalPlusMinus", 0),
                # Team totals for Usage%
                "team_fgm": tt.get("fgm", 0),
                "team_fga": tt.get("fga", 0),
                "team_ftm": tt.get("ftm", 0),
                "team_fta": tt.get("fta", 0),
                "team_tov": tt.get("tov", 0),
            }
            for k in _PLAYER_STAT_KEYS:
                entry[k] = gs.get(k, 0)

            log["players"][slug]["games"].append(entry)

    # Team entries
    for tno_str in ["1", "2"]:
        team_info = team1_info if tno_str == "1" else team2_info
        opp_tno = "2" if tno_str == "1" else "1"
        opp_info = team1_info if opp_tno == "1" else team2_info
        team_name = team_info.get("name", "")
        opp_name = opp_info.get("name", "")

        ts = team_totals[tno_str]
        opp_ts = team_totals[opp_tno]

        team_score = team_info.get("score", 0)
        opp_score = opp_info.get("score", 0)

        from .generator import _slugify
        team_slug = _slugify(team_name)

        if team_slug not in log["teams"]:
            log["teams"][team_slug] = {
                "name": team_name,
                "games": [],
            }

        entry = {
            "game_id": game_id,
            "date": date,
            "opponent": opp_name,
            "won": team_score > opp_score,
            "pts": team_score,
            "opp_pts": opp_score,
        }
        for k in _TEAM_STAT_KEYS:
            entry[k] = ts.get(k, 0)
            entry[f"opp_{k}"] = opp_ts.get(k, 0)
        # pts is already set from score, override with actual score
        entry["pts"] = team_score
        entry["opp_pts"] = opp_score

        log["teams"][team_slug]["games"].append(entry)


def _make_player_slug(first_name: str, family_name: str, team_name: str) -> str:
    from .generator import _slugify
    return f"{_slugify(team_name)}-{_slugify(first_name)}-{_slugify(family_name)}"


def compute_player_season_stats(slug: str, player_data: dict) -> dict:
    """Compute full season stats for a player from their game log."""
    games = player_data.get("games", [])
    played = [g for g in games if not g.get("isDNP", False)]
    gp = len(played)

    if gp == 0:
        return {"gp": 0, "slug": slug,
                "firstName": player_data.get("firstName", ""),
                "familyName": player_data.get("familyName", ""),
                "team": player_data.get("team", "")}

    # Totals
    totals = {k: 0 for k in _PLAYER_STAT_KEYS}
    totals["minutes_seconds"] = 0
    totals["plus_minus"] = 0
    totals["team_fga"] = 0
    totals["team_fta"] = 0
    totals["team_tov"] = 0

    dd_games = []
    td_games = []
    fouls_out_games = []
    best = {k: {"value": 0, "game_id": ""} for k in
            ["pts", "reb", "oreb", "dreb", "ast", "stl", "blk",
             "fgm", "fga", "fg2m", "fg2a", "fg3m", "fg3a", "ftm", "fta",
             "minutes_seconds"]}

    for g in played:
        totals["minutes_seconds"] += g.get("minutes_seconds", 0)
        totals["plus_minus"] += g.get("plus_minus", 0)
        totals["team_fga"] += g.get("team_fga", 0)
        totals["team_fta"] += g.get("team_fta", 0)
        totals["team_tov"] += g.get("team_tov", 0)

        for k in _PLAYER_STAT_KEYS:
            totals[k] += g.get(k, 0)

        # Double/triple double: count how many of pts,reb,ast,stl >= 10
        dd_cats = sum(1 for cat in ["pts", "reb", "ast", "stl"]
                      if g.get(cat, 0) >= 10)
        if dd_cats >= 3:
            td_games.append(g["game_id"])
            dd_games.append(g["game_id"])
        elif dd_cats == 2:
            dd_games.append(g["game_id"])

        # Fouls out (5+ personal fouls)
        if g.get("pf", 0) >= 5:
            fouls_out_games.append(g["game_id"])

        # Best game
        for k in ["pts", "reb", "oreb", "dreb", "ast", "stl", "blk",
                  "fgm", "fga", "fg2m", "fg2a", "fg3m", "fg3a", "ftm", "fta",
                  "minutes_seconds"]:
            val = g.get(k, 0)
            if val > best[k]["value"]:
                best[k] = {"value": val, "game_id": g["game_id"]}

    # Percentages
    fg_pct = round(totals["fgm"] / totals["fga"] * 100, 1) if totals["fga"] else 0.0
    fg2_pct = round(totals["fg2m"] / totals["fg2a"] * 100, 1) if totals["fg2a"] else 0.0
    fg3_pct = round(totals["fg3m"] / totals["fg3a"] * 100, 1) if totals["fg3a"] else 0.0
    ft_pct = round(totals["ftm"] / totals["fta"] * 100, 1) if totals["fta"] else 0.0

    # Advanced
    ts_denom = 2 * (totals["fga"] + 0.44 * totals["fta"])
    ts_pct = round(totals["pts"] / ts_denom * 100, 1) if ts_denom else 0.0

    efg_pct = round((totals["fgm"] + 0.5 * totals["fg3m"]) / totals["fga"] * 100, 1) if totals["fga"] else 0.0

    team_denom = totals["team_fga"] + 0.44 * totals["team_fta"] + totals["team_tov"]
    usage_pct = round(
        (totals["fga"] + 0.44 * totals["fta"] + totals["tov"]) / team_denom * 100, 1
    ) if team_denom else 0.0

    per = round(
        (totals["pts"] + totals["reb"] + totals["ast"] + totals["stl"] + totals["blk"]
         - (totals["fga"] - totals["fgm"])
         - (totals["fta"] - totals["ftm"])
         - totals["tov"]) / gp, 2
    )

    avg_seconds = totals["minutes_seconds"] / gp
    avg_min = int(avg_seconds // 60)
    avg_sec = int(avg_seconds % 60)

    return {
        "slug": slug,
        "firstName": player_data.get("firstName", ""),
        "familyName": player_data.get("familyName", ""),
        "team": player_data.get("team", ""),
        "gp": gp,
        # Totals
        "totalMinutes": totals["minutes_seconds"],
        "pts": totals["pts"],
        "reb": totals["reb"],
        "oreb": totals["oreb"],
        "dreb": totals["dreb"],
        "ast": totals["ast"],
        "stl": totals["stl"],
        "blk": totals["blk"],
        "tov": totals["tov"],
        "pf": totals["pf"],
        "pfd": totals["pfd"],
        "technical": totals["technical"],
        "fgm": totals["fgm"],
        "fga": totals["fga"],
        "fg2m": totals["fg2m"],
        "fg2a": totals["fg2a"],
        "fg3m": totals["fg3m"],
        "fg3a": totals["fg3a"],
        "ftm": totals["ftm"],
        "fta": totals["fta"],
        "plusMinus": totals["plus_minus"],
        # Averages
        "minPerGame": f"{avg_min}:{avg_sec:02d}",
        "ptsPerGame": round(totals["pts"] / gp, 1),
        "rebPerGame": round(totals["reb"] / gp, 1),
        "orebPerGame": round(totals["oreb"] / gp, 1),
        "drebPerGame": round(totals["dreb"] / gp, 1),
        "astPerGame": round(totals["ast"] / gp, 1),
        "stlPerGame": round(totals["stl"] / gp, 1),
        "blkPerGame": round(totals["blk"] / gp, 1),
        "tovPerGame": round(totals["tov"] / gp, 1),
        "pfPerGame": round(totals["pf"] / gp, 1),
        "pfdPerGame": round(totals["pfd"] / gp, 1),
        "fg2PerGame": round(totals["fg2m"] / gp, 1),
        "fg3PerGame": round(totals["fg3m"] / gp, 1),
        "ftPerGame": round(totals["fta"] / gp, 1),
        "ftmPerGame": round(totals["ftm"] / gp, 1),
        "plusMinusPerGame": round(totals["plus_minus"] / gp, 1),
        # Percentages
        "fgPct": fg_pct,
        "fg2Pct": fg2_pct,
        "fg3Pct": fg3_pct,
        "ftPct": ft_pct,
        # Advanced
        "tsPct": ts_pct,
        "efgPct": efg_pct,
        "usagePct": usage_pct,
        "per": per,
        # Milestones
        "doubleDoubles": len(dd_games),
        "doubleDoubleGames": dd_games,
        "tripleDoubles": len(td_games),
        "tripleDoubleGames": td_games,
        "foulsOut": len(fouls_out_games),
        "foulsOutGames": fouls_out_games,
        # Best game
        "best": best,
    }


def compute_team_season_stats(slug: str, team_data: dict) -> dict:
    """Compute full season stats for a team from their game log."""
    games = team_data.get("games", [])
    gp = len(games)

    if gp == 0:
        return {"gp": 0, "slug": slug, "name": team_data.get("name", "")}

    wins = 0
    totals = {k: 0 for k in _TEAM_STAT_KEYS}
    opp_totals = {k: 0 for k in _TEAM_STAT_KEYS}
    total_pts = 0
    total_opp_pts = 0

    for g in games:
        if g.get("won"):
            wins += 1
        total_pts += g.get("pts", 0)
        total_opp_pts += g.get("opp_pts", 0)
        for k in _TEAM_STAT_KEYS:
            totals[k] += g.get(k, 0)
            opp_totals[k] += g.get(f"opp_{k}", 0)

    # Override pts with actual score totals
    totals["pts"] = total_pts
    opp_totals["pts"] = total_opp_pts

    # Percentages
    def pct(made, att):
        return round(made / att * 100, 1) if att else 0.0

    # Possessions and pace
    team_poss_total = 0.0
    opp_poss_total = 0.0
    total_minutes = 0.0

    for g in games:
        t_fga = g.get("fga", 0)
        t_oreb = g.get("oreb", 0)
        t_tov = g.get("tov", 0)
        t_fta = g.get("fta", 0)
        opp_dreb = g.get("opp_dreb", 0)

        o_fga = g.get("opp_fga", 0)
        o_oreb = g.get("opp_oreb", 0)
        o_tov = g.get("opp_tov", 0)
        o_fta = g.get("opp_fta", 0)
        t_dreb = g.get("dreb", 0)

        denom_t = t_oreb + opp_dreb
        denom_o = o_oreb + t_dreb

        team_poss = t_fga + 0.44 * t_fta - (1.07 * t_oreb / denom_t * t_fga if denom_t else 0) + t_tov
        opp_poss = o_fga + 0.44 * o_fta - (1.07 * o_oreb / denom_o * o_fga if denom_o else 0) + o_tov

        team_poss_total += team_poss
        opp_poss_total += opp_poss
        total_minutes += 40.0  # Simplified; OT games use 40 as base

    pace = round(40 * ((team_poss_total + opp_poss_total) / 2) / total_minutes, 1) if total_minutes else 0.0
    ortg = round(total_pts / team_poss_total * 100, 1) if team_poss_total else 0.0
    drtg = round(total_opp_pts / opp_poss_total * 100, 1) if opp_poss_total else 0.0
    net_rtg = round(ortg - drtg, 1)

    return {
        "slug": slug,
        "name": team_data.get("name", ""),
        "gp": gp,
        "wins": wins,
        "losses": gp - wins,
        # Totals
        "pts": total_pts,
        "opp_pts": total_opp_pts,
        **{k: totals[k] for k in _TEAM_STAT_KEYS if k != "pts"},
        **{f"opp_{k}": opp_totals[k] for k in _TEAM_STAT_KEYS if k != "pts"},
        # Averages
        "ptsPerGame": round(total_pts / gp, 1),
        "opp_ptsPerGame": round(total_opp_pts / gp, 1),
        **{f"{k}PerGame": round(totals[k] / gp, 1) for k in _TEAM_STAT_KEYS if k != "pts"},
        **{f"opp_{k}PerGame": round(opp_totals[k] / gp, 1) for k in _TEAM_STAT_KEYS if k != "pts"},
        # Percentages
        "fgPct": pct(totals["fgm"], totals["fga"]),
        "fg2Pct": pct(totals["fg2m"], totals["fg2a"]),
        "fg3Pct": pct(totals["fg3m"], totals["fg3a"]),
        "ftPct": pct(totals["ftm"], totals["fta"]),
        "opp_fgPct": pct(opp_totals["fgm"], opp_totals["fga"]),
        "opp_fg3Pct": pct(opp_totals["fg3m"], opp_totals["fg3a"]),
        "opp_ftPct": pct(opp_totals["ftm"], opp_totals["fta"]),
        # Advanced
        "pace": pace,
        "ortg": ortg,
        "drtg": drtg,
        "netRtg": net_rtg,
    }
