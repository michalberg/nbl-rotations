"""Lineup statistics: on/off ratings and combo analysis from minute-level data."""

import unicodedata
from collections import defaultdict
from itertools import combinations

PRIOR_WEIGHT = 85  # minutes, calibrated for NBL season length


def _slugify(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return ascii_str.lower().replace(" ", "-").replace("'", "").replace(".", "")


def _poss(fga: float, oreb: float, tov: float, fta: float, opp_dreb: float) -> float:
    """Possession estimate with oreb correction (same formula as stats.py)."""
    denom = oreb + opp_dreb
    oreb_adj = 1.07 * oreb / denom * fga if denom else 0.0
    return fga + 0.44 * fta - oreb_adj + tov


def _minute_team_stats(players_by_name: dict, lineup: list, minute_idx: int) -> dict:
    """Sum raw stat components for players in lineup at minute_idx."""
    pts = fga = fta = oreb = dreb = tov = 0.0
    for name in lineup:
        p = players_by_name.get(name)
        if p is None:
            continue
        mins = p.get("minutes", [])
        if minute_idx >= len(mins):
            continue
        m = mins[minute_idx]
        stats = m.get("stats", {})
        pts  += m.get("pts", 0)
        fga  += stats.get("fga",  0)
        fta  += stats.get("fta",  0)
        oreb += stats.get("oreb", 0)
        dreb += stats.get("dreb", 0)
        tov  += stats.get("tov",  0)
    return {"pts": pts, "fga": fga, "fta": fta, "oreb": oreb, "dreb": dreb, "tov": tov}


def _team_box_score(game_json: dict, tno: str) -> dict:
    """Sum gameStats across all players of a team (box-score level)."""
    pts = fga = fta = oreb = dreb = tov = 0.0
    for p in game_json.get("players", {}).get(tno, []):
        gs = p.get("gameStats", {})
        pts  += gs.get("pts",  0)
        fga  += gs.get("fga",  0)
        fta  += gs.get("fta",  0)
        oreb += gs.get("oreb", 0)
        dreb += gs.get("dreb", 0)
        tov  += gs.get("tov",  0)
    return {"pts": pts, "fga": fga, "fta": fta, "oreb": oreb, "dreb": dreb, "tov": tov}


def _stabilize(raw_net: float, prior: float, minutes: int) -> tuple[float, float, str]:
    """Return (stabilized_net, weight, confidence)."""
    w = minutes / (minutes + PRIOR_WEIGHT)
    stab = round(w * raw_net + (1 - w) * prior, 1)
    if w < 0.35:
        conf = "Low"
    elif w < 0.55:
        conf = "Medium"
    elif w < 0.70:
        conf = "High"
    else:
        conf = "Very High"
    return stab, round(w, 2), conf


def _player_on_net(player_name: str, team_slug: str, season_onoff: dict) -> float | None:
    """Return player's on-court net rating, or None if insufficient data."""
    od = season_onoff.get(f"{team_slug}|{player_name}")
    if not od:
        return None
    on = od["on"]
    if on["poss"] <= 0 or on["opp_poss"] <= 0:
        return None
    return on["pts"] / on["poss"] * 100 - on["opp_pts"] / on["opp_poss"] * 100


def _combo_prior(
    players: list,
    team_slug: str,
    team_net_rtg: float,
    team_avg_on_net: float | None,
    season_onoff: dict,
) -> float:
    """Compute prior = team_net + avg(player_on_net - team_avg_on_net).
    Falls back to team_net if on/off data is unavailable.
    """
    if not season_onoff or team_avg_on_net is None:
        return round(team_net_rtg, 1)
    deltas = []
    for p in players:
        pnet = _player_on_net(p, team_slug, season_onoff)
        if pnet is not None:
            deltas.append(pnet - team_avg_on_net)
    if not deltas:
        return round(team_net_rtg, 1)
    return round(team_net_rtg + sum(deltas) / len(deltas), 1)


def compute_game_lineup_stats(game_json: dict) -> dict:
    """For each minute return lineup and team/opp pts+poss for both teams.

    Returns dict["1"|"2"] = list of:
        {"lineup": tuple(sorted names), "team_pts", "opp_pts", "team_poss", "opp_poss"}
    """
    result = {}
    for tno in ["1", "2"]:
        opp_tno = "2" if tno == "1" else "1"
        lineups_arr = game_json.get("lineups", {}).get(tno, [])
        opp_lineups_arr = game_json.get("lineups", {}).get(opp_tno, [])

        players_by_name = {
            p["name"]: p
            for p in game_json.get("players", {}).get(tno, [])
            if p.get("name")
        }
        opp_players_by_name = {
            p["name"]: p
            for p in game_json.get("players", {}).get(opp_tno, [])
            if p.get("name")
        }

        minute_dicts = []
        for m_idx, lineup in enumerate(lineups_arr):
            if not lineup:
                continue
            opp_lineup = opp_lineups_arr[m_idx] if m_idx < len(opp_lineups_arr) else []
            t = _minute_team_stats(players_by_name, lineup, m_idx)
            o = _minute_team_stats(opp_players_by_name, opp_lineup, m_idx)
            team_poss = _poss(t["fga"], t["oreb"], t["tov"], t["fta"], o["dreb"])
            opp_poss  = _poss(o["fga"], o["oreb"], o["tov"], o["fta"], t["dreb"])
            minute_dicts.append({
                "lineup":    tuple(sorted(lineup)),
                "team_pts":  t["pts"],
                "opp_pts":   o["pts"],
                "team_poss": team_poss,
                "opp_poss":  opp_poss,
            })
        result[tno] = minute_dicts
    return result


def _new_accum() -> dict:
    return {"pts": 0.0, "opp_pts": 0.0, "poss": 0.0, "opp_poss": 0.0, "minutes": 0}


def aggregate_season_lineups(all_games_data: list, season_onoff: dict | None = None) -> dict:
    """Aggregate lineup combo stats across all games per team.

    Team-level ORTG/DRTG/Net are computed from box-score data.
    Combo ratings use per-minute lineup data with Stabilized Net Rating.

    Pass season_onoff (from compute_season_onoff) to enable player-adjusted priors.

    Returns dict[team_slug] = {
        "name", "slug", "ortg", "drtg", "net_rtg", "games", "total_minutes",
        "lineups": {2: [...], 3: [...], 4: [...], 5: [...]}
    }
    Each lineup entry: {
        "players", "minutes",
        "raw_ortg", "raw_drtg", "raw_net",
        "prior", "stabilized_net", "weight", "confidence"
    }
    """
    team_data: dict[str, dict] = {}
    team_box: dict[str, dict] = {}

    for game_json in all_games_data:
        game_stats = compute_game_lineup_stats(game_json)

        for tno in ["1", "2"]:
            opp_tno = "2" if tno == "1" else "1"
            team_info = game_json.get(f"team{tno}", {})
            team_name = team_info.get("name", "")
            if not team_name:
                continue
            team_slug = _slugify(team_name)

            # ── Box-score team ratings ────────────────────────────────────
            t_box = _team_box_score(game_json, tno)
            o_box = _team_box_score(game_json, opp_tno)
            t_poss_box = _poss(t_box["fga"], t_box["oreb"], t_box["tov"], t_box["fta"], o_box["dreb"])
            o_poss_box = _poss(o_box["fga"], o_box["oreb"], o_box["tov"], o_box["fta"], t_box["dreb"])

            if team_slug not in team_box:
                team_box[team_slug] = {"pts": 0.0, "poss": 0.0, "opp_pts": 0.0, "opp_poss": 0.0,
                                       "games": 0, "total_minutes": 0}
            team_box[team_slug]["pts"]           += t_box["pts"]
            team_box[team_slug]["poss"]          += t_poss_box
            team_box[team_slug]["opp_pts"]       += o_box["pts"]
            team_box[team_slug]["opp_poss"]      += o_poss_box
            team_box[team_slug]["games"]         += 1
            team_box[team_slug]["total_minutes"] += game_json.get("totalMinutes", 40)

            # ── Per-minute combo accumulation ─────────────────────────────
            if team_slug not in team_data:
                team_data[team_slug] = {
                    "name": team_name,
                    "slug": team_slug,
                    "combos": {
                        2: defaultdict(_new_accum),
                        3: defaultdict(_new_accum),
                        4: defaultdict(_new_accum),
                        5: defaultdict(_new_accum),
                    },
                }

            for mdict in game_stats.get(tno, []):
                lineup = mdict["lineup"]
                if len(lineup) != 5:
                    continue

                t_pts  = mdict["team_pts"]
                o_pts  = mdict["opp_pts"]
                t_poss = mdict["team_poss"]
                o_poss = mdict["opp_poss"]

                for size in [2, 3, 4, 5]:
                    for combo in combinations(lineup, size):
                        combo_key = tuple(sorted(combo))
                        d = team_data[team_slug]["combos"][size][combo_key]
                        d["pts"]      += t_pts
                        d["opp_pts"]  += o_pts
                        d["poss"]     += t_poss
                        d["opp_poss"] += o_poss
                        d["minutes"]  += 1

    result = {}
    for slug, td in team_data.items():
        box = team_box.get(slug, {})
        ortg    = round(box["pts"]     / box["poss"]     * 100, 1) if box.get("poss",     0) > 0 else 0.0
        drtg    = round(box["opp_pts"] / box["opp_poss"] * 100, 1) if box.get("opp_poss", 0) > 0 else 0.0
        net_rtg = round(ortg - drtg, 1)

        # Team average on-net across all players (for prior computation)
        team_avg_on_net: float | None = None
        if season_onoff:
            on_nets = [
                od["on"]["pts"] / od["on"]["poss"] * 100
                - od["on"]["opp_pts"] / od["on"]["opp_poss"] * 100
                for key, od in season_onoff.items()
                if key.startswith(f"{slug}|")
                and od["on"]["poss"] > 0 and od["on"]["opp_poss"] > 0
            ]
            if on_nets:
                team_avg_on_net = sum(on_nets) / len(on_nets)

        lineups: dict[int, list] = {}
        for size in [2, 3, 4, 5]:
            entries = []
            for combo_key, d in td["combos"][size].items():
                if d["poss"] <= 0 or d["opp_poss"] <= 0:
                    continue
                raw_ortg = round(d["pts"]     / d["poss"]     * 100, 1)
                raw_drtg = round(d["opp_pts"] / d["opp_poss"] * 100, 1)
                raw_net  = round(raw_ortg - raw_drtg, 1)
                prior    = _combo_prior(
                    list(combo_key), slug, net_rtg, team_avg_on_net, season_onoff or {}
                )
                stab, w, conf = _stabilize(raw_net, prior, d["minutes"])
                entries.append({
                    "players":        list(combo_key),
                    "minutes":        d["minutes"],
                    "raw_ortg":       raw_ortg,
                    "raw_drtg":       raw_drtg,
                    "raw_net":        raw_net,
                    "prior":          prior,
                    "stabilized_net": stab,
                    "weight":         w,
                    "confidence":     conf,
                })
            entries.sort(key=lambda x: -x["stabilized_net"])
            lineups[size] = entries

        result[slug] = {
            "name":          td["name"],
            "slug":          slug,
            "ortg":          ortg,
            "drtg":          drtg,
            "net_rtg":       net_rtg,
            "games":         box.get("games", 0),
            "total_minutes": box.get("total_minutes", 0),
            "lineups":       lineups,
        }

    return result


def compute_season_onoff(all_games_data: list) -> dict:
    """Compute per-player on/off stats across the season.

    Returns dict["{team_slug}|{short_name}"] = {
        "on":  {"pts", "poss", "opp_pts", "opp_poss", "minutes"},
        "off": {"pts", "poss", "opp_pts", "opp_poss", "minutes"},
    }
    """
    onoff: dict[str, dict] = defaultdict(lambda: {
        "on":  _new_accum(),
        "off": _new_accum(),
    })

    for game_json in all_games_data:
        for tno in ["1", "2"]:
            team_info = game_json.get(f"team{tno}", {})
            team_name = team_info.get("name", "")
            if not team_name:
                continue
            team_slug = _slugify(team_name)

            opp_tno = "2" if tno == "1" else "1"
            lineups_arr     = game_json.get("lineups", {}).get(tno, [])
            opp_lineups_arr = game_json.get("lineups", {}).get(opp_tno, [])

            players_by_name = {
                p["name"]: p
                for p in game_json.get("players", {}).get(tno, [])
                if p.get("name")
            }
            opp_players_by_name = {
                p["name"]: p
                for p in game_json.get("players", {}).get(opp_tno, [])
                if p.get("name")
            }

            all_player_names: set[str] = set()
            for lineup in lineups_arr:
                all_player_names.update(lineup)

            for m_idx, lineup in enumerate(lineups_arr):
                if not lineup or len(lineup) != 5:
                    continue
                lineup_set = set(lineup)
                opp_lineup = opp_lineups_arr[m_idx] if m_idx < len(opp_lineups_arr) else []

                t = _minute_team_stats(players_by_name, lineup, m_idx)
                o = _minute_team_stats(opp_players_by_name, opp_lineup, m_idx)
                t_poss = _poss(t["fga"], t["oreb"], t["tov"], t["fta"], o["dreb"])
                o_poss = _poss(o["fga"], o["oreb"], o["tov"], o["fta"], t["dreb"])

                for player_name in all_player_names:
                    key  = f"{team_slug}|{player_name}"
                    side = "on" if player_name in lineup_set else "off"
                    onoff[key][side]["pts"]      += t["pts"]
                    onoff[key][side]["poss"]     += t_poss
                    onoff[key][side]["opp_pts"]  += o["pts"]
                    onoff[key][side]["opp_poss"] += o_poss
                    onoff[key][side]["minutes"]  += 1

    return dict(onoff)
