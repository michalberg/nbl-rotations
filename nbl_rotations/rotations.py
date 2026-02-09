"""Calculate player rotation stints from PBP substitution events."""

from dataclasses import dataclass, field

from .parser import GameData, Player, parse_time_to_seconds


@dataclass
class Stint:
    shirt_number: str
    player_name: str
    team_number: int
    period_in: int
    period_out: int
    time_in: float  # absolute seconds from game start
    time_out: float
    score_team_in: int
    score_opp_in: int
    score_team_out: int
    score_opp_out: int

    @property
    def duration(self) -> float:
        return self.time_out - self.time_in

    @property
    def plus_minus(self) -> int:
        team_delta = self.score_team_out - self.score_team_in
        opp_delta = self.score_opp_out - self.score_opp_in
        return team_delta - opp_delta


@dataclass
class PlayerRotation:
    shirt_number: str
    player_name: str
    team_number: int
    is_starter: bool
    total_seconds: float = 0.0
    stints: list[Stint] = field(default_factory=list)


def _period_end_seconds(period: int) -> float:
    """Get absolute seconds at end of a given period."""
    total = 0.0
    for p in range(1, period + 1):
        total += 300.0 if p >= 5 else 600.0
    return total


def _period_start_seconds(period: int) -> float:
    """Get absolute seconds at start of a given period."""
    total = 0.0
    for p in range(1, period):
        total += 300.0 if p >= 5 else 600.0
    return total


def _current_score_for_team(score1: int, score2: int, team_number: int) -> tuple[int, int]:
    """Return (team_score, opp_score) for the given team number."""
    if team_number == 1:
        return score1, score2
    return score2, score1


def calculate_rotations(game: GameData) -> dict[int, list[PlayerRotation]]:
    """Calculate rotation stints for each team.

    Returns dict with keys 1 and 2, each containing a list of PlayerRotation.
    """
    result: dict[int, list[PlayerRotation]] = {1: [], 2: []}

    for tno in [1, 2]:
        team_players = [p for p in game.players if p.team_number == tno]
        # Track who is on court: shirt_number -> True/False
        on_court: dict[str, bool] = {}
        # Track current stint start info per player
        stint_start: dict[str, dict] = {}

        # Build player rotation objects
        rotations: dict[str, PlayerRotation] = {}
        for p in team_players:
            pr = PlayerRotation(
                shirt_number=p.shirt_number,
                player_name=p.name,
                team_number=tno,
                is_starter=p.is_starter,
            )
            rotations[p.shirt_number] = pr

        # Initialize starters
        for p in team_players:
            if p.is_starter:
                on_court[p.shirt_number] = True
                stint_start[p.shirt_number] = {
                    "time": 0.0,
                    "period": 1,
                    "score_team": 0,
                    "score_opp": 0,
                }

        # Track last known score
        last_score1, last_score2 = 0, 0

        # Process events
        for event in game.events:
            if event.score1 + event.score2 > 0:
                last_score1, last_score2 = event.score1, event.score2

            if event.action_type == "substitution" and event.team_number == tno:
                abs_time = parse_time_to_seconds(event.game_time, event.period)
                team_score, opp_score = _current_score_for_team(last_score1, last_score2, tno)

                if event.sub_type == "out" and event.shirt_number in on_court:
                    # Player going out - close their stint
                    sn = event.shirt_number
                    if sn in stint_start:
                        start = stint_start[sn]
                        stint = Stint(
                            shirt_number=sn,
                            player_name=rotations[sn].player_name if sn in rotations else event.player_name,
                            team_number=tno,
                            period_in=start["period"],
                            period_out=event.period,
                            time_in=start["time"],
                            time_out=abs_time,
                            score_team_in=start["score_team"],
                            score_opp_in=start["score_opp"],
                            score_team_out=team_score,
                            score_opp_out=opp_score,
                        )
                        if sn in rotations:
                            rotations[sn].stints.append(stint)
                        del stint_start[sn]
                    del on_court[sn]

                elif event.sub_type == "in":
                    # Player coming in
                    sn = event.shirt_number
                    on_court[sn] = True
                    stint_start[sn] = {
                        "time": abs_time,
                        "period": event.period,
                        "score_team": team_score,
                        "score_opp": opp_score,
                    }

        # Close any open stints at end of game
        game_end = _period_end_seconds(game.num_periods)
        team_score, opp_score = _current_score_for_team(
            game.final_score1, game.final_score2, tno
        )
        for sn in list(stint_start.keys()):
            start = stint_start[sn]
            stint = Stint(
                shirt_number=sn,
                player_name=rotations[sn].player_name if sn in rotations else sn,
                team_number=tno,
                period_in=start["period"],
                period_out=game.num_periods,
                time_in=start["time"],
                time_out=game_end,
                score_team_in=start["score_team"],
                score_opp_in=start["score_opp"],
                score_team_out=team_score,
                score_opp_out=opp_score,
            )
            if sn in rotations:
                rotations[sn].stints.append(stint)

        # Calculate total seconds
        for pr in rotations.values():
            pr.total_seconds = sum(s.duration for s in pr.stints)

        # Sort: starters first (by minutes desc), then bench by total_seconds desc
        starters = sorted(
            [r for r in rotations.values() if r.is_starter],
            key=lambda r: -r.total_seconds,
        )
        bench = sorted(
            [r for r in rotations.values() if not r.is_starter and r.total_seconds > 0],
            key=lambda r: -r.total_seconds,
        )
        result[tno] = starters + bench

    return result
