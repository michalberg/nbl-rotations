"""Parse raw FIBA LiveStats JSON into structured game data."""

from dataclasses import dataclass, field


@dataclass
class Player:
    shirt_number: str
    name: str
    is_starter: bool
    team_number: int  # 1 or 2
    stats_minutes: str = ""  # sMinutes from player stats


@dataclass
class Event:
    action_number: int
    game_time: str  # "MM:SS"
    period: int
    team_number: int  # 0, 1, or 2
    action_type: str
    sub_type: str
    success: int
    score1: int  # team 1 score
    score2: int  # team 2 score
    shirt_number: str = ""
    player_name: str = ""


@dataclass
class GameData:
    game_id: str
    team1_name: str
    team2_name: str
    team1_code: str
    team2_code: str
    final_score1: int
    final_score2: int
    num_periods: int
    players: list[Player] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)


def parse_time_to_seconds(gt: str, period: int, period_duration: int = 600) -> float:
    """Convert game time + period to absolute seconds from game start.

    gt is countdown time within the period (e.g., "10:00" = start, "00:00" = end).
    OT periods (5+) are 5 minutes, counting down from "05:00".
    """
    parts = gt.split(":")
    minutes = int(parts[0])
    seconds = int(parts[1]) if len(parts) > 1 else 0
    remaining = minutes * 60 + seconds
    # OT periods are 5 minutes (300s), regular quarters 10 minutes (600s)
    current_duration = 300 if period >= 5 else period_duration
    elapsed_in_period = current_duration - remaining
    total_before = 0
    for p in range(1, period):
        total_before += 300 if p >= 5 else period_duration
    return total_before + elapsed_in_period


def _fix_period_numbers(pbp: list[dict]) -> list[dict]:
    """Fix period numbers for OT games where FIBA API resets period to 1.

    Detects actual periods from 'period end' events and reassigns
    the correct period number to all events. Substitutions between
    'period end' and 'period start' belong to the next period.
    """
    sorted_pbp = sorted(pbp, key=lambda e: e.get("actionNumber", 0))

    # Find period end events to determine boundaries
    period_ends = []
    for e in sorted_pbp:
        if e.get("actionType") == "period" and e.get("subType") == "end":
            period_ends.append(e.get("actionNumber", 0))

    # If 4 or fewer period ends, no OT — periods are already correct
    if len(period_ends) <= 4:
        return pbp

    # Reassign period numbers based on period end boundaries
    # Events up to and including first period end = period 1
    # Events after Nth period end = period N+1
    num_real_periods = len(period_ends)
    fixed = []
    for e in pbp:
        e = dict(e)  # don't mutate original
        an = e.get("actionNumber", 0)
        real_period = 1
        for end_an in period_ends:
            if an > end_an:
                real_period += 1
        # Cap at the last real period (game end event comes after last period end)
        e["period"] = min(real_period, num_real_periods)
        fixed.append(e)

    return fixed


def parse_game(raw: dict, game_id: str = "") -> GameData:
    """Parse raw JSON into GameData."""
    tm1 = raw.get("tm", {}).get("1", {})
    tm2 = raw.get("tm", {}).get("2", {})

    # Fix period numbers (FIBA API resets to 1 for OT)
    pbp = _fix_period_numbers(raw.get("pbp", []))

    # Determine number of periods from PBP data
    num_periods = max((e.get("period", 1) for e in pbp), default=4)

    # Final score (API returns scores as strings)
    final_s1 = 0
    final_s2 = 0
    if pbp:
        # Find the last event with scores (pbp is descending by actionNumber)
        for e in pbp:
            s1_raw = e.get("s1")
            s2_raw = e.get("s2")
            if s1_raw is not None and s2_raw is not None and s1_raw != "" and s2_raw != "":
                s1 = int(s1_raw)
                s2 = int(s2_raw)
                if s1 + s2 > final_s1 + final_s2:
                    final_s1, final_s2 = s1, s2

    game = GameData(
        game_id=game_id,
        team1_name=tm1.get("name", "Team 1"),
        team2_name=tm2.get("name", "Team 2"),
        team1_code=tm1.get("code", tm1.get("shortName", "T1")),
        team2_code=tm2.get("code", tm2.get("shortName", "T2")),
        final_score1=final_s1,
        final_score2=final_s2,
        num_periods=num_periods,
    )

    # Parse players
    for tno_str, tm in [("1", tm1), ("2", tm2)]:
        tno = int(tno_str)
        pl_data = tm.get("pl", {})
        for _key, pl in pl_data.items():
            stats_minutes = ""
            if "sMinutes" in pl:
                stats_minutes = pl["sMinutes"]

            player = Player(
                shirt_number=str(pl.get("shirtNumber", "")),
                name=pl.get("name", pl.get("scoreboardName", f"#{pl.get('shirtNumber', '?')}")),
                is_starter=pl.get("starter", 0) == 1,
                team_number=tno,
                stats_minutes=stats_minutes,
            )
            game.players.append(player)

    # Parse PBP events (sorted ascending by actionNumber)
    sorted_pbp = sorted(pbp, key=lambda e: e.get("actionNumber", 0))
    for e in sorted_pbp:
        event = Event(
            action_number=e.get("actionNumber", 0),
            game_time=e.get("gt", "00:00"),
            period=e.get("period", 1),
            team_number=e.get("tno", 0),
            action_type=e.get("actionType", ""),
            sub_type=e.get("subType", ""),
            success=e.get("success", 0),
            score1=int(e.get("s1") or 0),
            score2=int(e.get("s2") or 0),
            shirt_number=str(e.get("shirtNumber", "")),
            player_name=e.get("scoreboardName", e.get("name", "")),
        )
        game.events.append(event)

    return game
