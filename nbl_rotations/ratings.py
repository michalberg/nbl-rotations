"""Calculate Offensive/Defensive Rating per stint and per lineup."""

from dataclasses import dataclass, field

from .parser import GameData, Event, parse_time_to_seconds
from .rotations import PlayerRotation, Stint


@dataclass
class StintRating:
    """Rating data for a single stint."""
    possessions: float = 0.0
    points_for: int = 0
    points_against: int = 0
    ortg: float = 0.0
    drtg: float = 0.0


@dataclass
class PlayerRating:
    """Aggregated rating for a player."""
    shirt_number: str
    player_name: str
    team_number: int
    total_seconds: float = 0.0
    total_possessions: float = 0.0
    total_points_for: int = 0
    total_points_against: int = 0
    ortg: float = 0.0
    drtg: float = 0.0
    net_rating: float = 0.0


def _count_possessions_in_range(
    events: list[Event], team_number: int,
    time_start: float, time_end: float
) -> float:
    """Count possessions for a team in a time range.

    Possessions = FGA - OREB + TO + 0.44 * FTA
    """
    fga = 0
    oreb = 0
    to = 0
    fta = 0

    for e in events:
        if e.team_number != team_number:
            continue
        abs_time = parse_time_to_seconds(e.game_time, e.period)
        if abs_time < time_start or abs_time > time_end:
            continue

        if e.action_type in ("2pt", "3pt"):
            fga += 1
        elif e.action_type == "freethrow":
            fta += 1
        elif e.action_type == "rebound" and e.sub_type == "offensive":
            oreb += 1
        elif e.action_type == "turnover":
            to += 1

    return fga - oreb + to + 0.44 * fta


def calculate_stint_rating(stint: Stint, events: list[Event]) -> StintRating:
    """Calculate rating for a single stint."""
    rating = StintRating()

    rating.points_for = stint.score_team_out - stint.score_team_in
    rating.points_against = stint.score_opp_out - stint.score_opp_in

    # Count team possessions for ORTG
    team_poss = _count_possessions_in_range(
        events, stint.team_number, stint.time_in, stint.time_out
    )
    # Count opponent possessions for DRTG
    opp_tno = 2 if stint.team_number == 1 else 1
    opp_poss = _count_possessions_in_range(
        events, opp_tno, stint.time_in, stint.time_out
    )

    rating.possessions = team_poss

    if team_poss > 0:
        rating.ortg = (rating.points_for / team_poss) * 100
    if opp_poss > 0:
        rating.drtg = (rating.points_against / opp_poss) * 100

    return rating


def calculate_player_ratings(
    rotations: dict[int, list[PlayerRotation]],
    game: GameData,
) -> dict[int, list[PlayerRating]]:
    """Calculate aggregated ratings per player."""
    result: dict[int, list[PlayerRating]] = {}

    for tno, players in rotations.items():
        ratings = []
        for pr in players:
            player_rating = PlayerRating(
                shirt_number=pr.shirt_number,
                player_name=pr.player_name,
                team_number=tno,
                total_seconds=pr.total_seconds,
            )

            for stint in pr.stints:
                sr = calculate_stint_rating(stint, game.events)
                player_rating.total_possessions += sr.possessions
                player_rating.total_points_for += sr.points_for
                player_rating.total_points_against += sr.points_against

            if player_rating.total_possessions > 0:
                player_rating.ortg = (
                    player_rating.total_points_for / player_rating.total_possessions
                ) * 100
                player_rating.drtg = (
                    player_rating.total_points_against / player_rating.total_possessions
                ) * 100
                player_rating.net_rating = player_rating.ortg - player_rating.drtg

            ratings.append(player_rating)

        result[tno] = ratings

    return result
