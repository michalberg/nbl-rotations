#!/usr/bin/env python3
"""NBL Rotations - CLI entry point."""

import argparse
import sys

from nbl_rotations.fetcher import fetch_game, load_game_ids
from nbl_rotations.parser import parse_game
from nbl_rotations.rotations import calculate_rotations
from nbl_rotations.ratings import calculate_player_ratings
from nbl_rotations.generator import (
    build_game_json, generate_site, generate_index,
    generate_player_pages, generate_team_data,
)
from nbl_rotations.scraper import (
    scrape_finished_games, load_games_json, update_games,
)


def process_game(game_id: str, date: str | None = None) -> dict:
    """Fetch, parse, and process a single game. Returns game JSON data."""
    print(f"Processing game {game_id}...")

    print(f"  Fetching data...")
    raw = fetch_game(game_id)

    print(f"  Parsing PBP...")
    game = parse_game(raw, game_id)
    print(f"  {game.team1_name} {game.final_score1} : {game.final_score2} {game.team2_name}")
    print(f"  {len(game.events)} events, {len(game.players)} players, {game.num_periods} periods")

    print(f"  Calculating rotations...")
    rotations = calculate_rotations(game)

    # Print stint validation
    for tno in [1, 2]:
        team_name = game.team1_name if tno == 1 else game.team2_name
        print(f"  {team_name}:")
        for pr in rotations[tno]:
            calc_min = pr.total_seconds / 60
            # Find sMinutes from player data
            matching = [p for p in game.players
                        if p.shirt_number == pr.shirt_number and p.team_number == tno]
            stats_min = matching[0].stats_minutes if matching else ""
            marker = ""
            if stats_min:
                try:
                    parts = stats_min.split(":")
                    stat_total = int(parts[0]) + int(parts[1]) / 60 if len(parts) == 2 else float(stats_min)
                    diff = abs(calc_min - stat_total)
                    if diff > 2:
                        marker = f" ⚠️ diff={diff:.1f}"
                except (ValueError, IndexError):
                    pass
            print(f"    #{pr.shirt_number} {pr.player_name}: {calc_min:.1f}min (stats: {stats_min}){marker}")

    print(f"  Calculating ratings...")
    ratings = calculate_player_ratings(rotations, game)

    print(f"  Building JSON...")
    game_json = build_game_json(game, rotations, ratings)

    # Attach date metadata if available
    if date:
        game_json["date"] = date

    return game_json


def main():
    parser = argparse.ArgumentParser(description="NBL Rotations - play-by-play analysis")
    parser.add_argument("games_file", nargs="?", help="Text file with game IDs (one per line)")
    parser.add_argument("--game-id", help="Process a single game by ID")
    parser.add_argument("--fetch-only", action="store_true", help="Only fetch data, don't generate HTML")
    parser.add_argument("--scrape", action="store_true", help="Scrape nbl.basketball for finished games")
    parser.add_argument("--generate", action="store_true", help="Generate HTML (use with --scrape for new games only)")
    parser.add_argument("--all", action="store_true", help="Process all games from games.json")
    args = parser.parse_args()

    # --scrape mode
    if args.scrape:
        print("Scraping nbl.basketball...")
        scraped = scrape_finished_games()
        print(f"  Found {len(scraped)} finished games on the web.")

        new_games = update_games(scraped)
        if new_games:
            print(f"  {len(new_games)} new games added to games.json:")
            for g in new_games:
                print(f"    {g['date']} {g['team1']} {g['score1']}:{g['score2']} {g['team2']} (ID: {g['game_id']})")
        else:
            print("  No new games found.")

        if args.generate and new_games:
            # Process only new games (fetch FIBA data + generate per-game HTML)
            new_games_data = []
            for g in new_games:
                game_json = process_game(g["game_id"], date=g["date"])
                new_games_data.append(game_json)

            print(f"\nGenerating {len(new_games_data)} new game pages...")
            generate_site(new_games_data)

            # Regenerate index with ALL games from games.json
            print("Regenerating index with all games...")
            generate_index(load_games_json())

            # Regenerate player/team pages from ALL game data
            print("Regenerating player and team pages...")
            all_games_data = _load_and_build_all_games()
            generate_player_pages(all_games_data)
            generate_team_data(all_games_data)
            print(f"\nDone! {len(new_games)} new games processed.")
        elif args.generate:
            print("  No new games to generate.")
        return

    # --all mode: process everything from games.json
    if args.all:
        all_games_data = _load_and_build_all_games()
        if not all_games_data:
            print("No games in games.json. Run --scrape first.")
            sys.exit(1)
        print(f"\nGenerating static site...")
        generate_site(all_games_data)
        print(f"\nGenerating player pages...")
        generate_player_pages(all_games_data)
        print(f"\nGenerating team data...")
        generate_team_data(all_games_data)
        print(f"\nDone! {len(all_games_data)} games processed.")
        return

    # Legacy mode: games_file or --game-id
    if not args.games_file and not args.game_id:
        parser.print_help()
        sys.exit(1)

    # Collect game IDs
    game_ids = []
    if args.game_id:
        game_ids.append(args.game_id)
    if args.games_file:
        game_ids.extend(load_game_ids(args.games_file))

    if not game_ids:
        print("No game IDs found.")
        sys.exit(1)

    if args.fetch_only:
        for gid in game_ids:
            print(f"Fetching game {gid}...")
            fetch_game(gid)
            print(f"  Cached.")
        return

    # Process all games
    games_data = []
    for gid in game_ids:
        game_json = process_game(gid)
        games_data.append(game_json)

    # Generate static site
    print("\nGenerating static site...")
    generate_site(games_data)
    print("\nGenerating player pages...")
    generate_player_pages(games_data)
    print("\nGenerating team data...")
    generate_team_data(games_data)
    print("\nDone! Open docs/index.html in your browser.")


def _load_and_build_all_games() -> list[dict]:
    """Load all games from games.json, process each, return list of game JSON data."""
    all_games = load_games_json()
    if not all_games:
        return []

    games_data = []
    for g in all_games:
        game_json = process_game(g["game_id"], date=g["date"])
        games_data.append(game_json)
    return games_data


if __name__ == "__main__":
    main()
