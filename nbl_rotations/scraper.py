"""Scrape finished games from nbl.basketball."""

import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

GAMES_URL = "https://nbl.basketball/zapasy?d_od=&d_do=&k=0"
GAMES_JSON = Path(__file__).parent.parent / "games.json"


def scrape_finished_games() -> list[dict]:
    """Scrape nbl.basketball and return list of finished games."""
    resp = requests.get(GAMES_URL, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    games = []
    for row in soup.select("tbody tr"):
        # Only finished games have a "review" link
        review_link = row.find("a", string=re.compile(r"review"))
        if not review_link:
            continue

        # Date from data-sort attribute
        date_td = row.find("td", attrs={"data-sort": True})
        if not date_td:
            continue
        data_sort = date_td["data-sort"]
        # Format: "2025-09-26-17-00" → "2025-09-26"
        date_parts = data_sort.split("-")
        if len(date_parts) < 3:
            continue
        date = "-".join(date_parts[:3])

        # Teams: find the td with team divs
        team_divs = []
        for td in row.find_all("td"):
            container = td.find("div", class_="d-flex")
            if container:
                inner = container.find("div", class_="")
                if inner:
                    divs = inner.find_all("div", recursive=False)
                    if len(divs) == 2:
                        team_divs = divs
                        break

        if len(team_divs) != 2:
            continue
        team1 = team_divs[0].get_text(strip=True)
        team2 = team_divs[1].get_text(strip=True)

        # Score: find the link to /zapas/... with score
        score_link = row.find("a", href=re.compile(r"/zapas/\d+#tab-pane-one"))
        if not score_link:
            continue
        score_bold = score_link.find("div", class_="font-weight-bold")
        if not score_bold:
            continue
        score2 = int(score_bold.get_text(strip=True))
        # Score1 is text before the div
        score_text = score_link.get_text(strip=True)
        score1_text = score_text.replace(str(score2), "", 1).strip()
        try:
            score1 = int(score1_text)
        except ValueError:
            continue

        # Livestats game ID from fibalivestats URL
        livestats_link = row.find("a", href=re.compile(r"fibalivestats\.com"))
        if not livestats_link:
            continue
        ls_match = re.search(r"/(\d+)/?$", livestats_link["href"])
        if not ls_match:
            continue
        game_id = ls_match.group(1)

        games.append({
            "game_id": game_id,
            "date": date,
            "team1": team1,
            "team2": team2,
            "score1": score1,
            "score2": score2,
        })

    return games


def load_games_json() -> list[dict]:
    """Load existing games.json, return empty list if not found."""
    if not GAMES_JSON.exists():
        return []
    with open(GAMES_JSON) as f:
        return json.load(f)


def save_games_json(games: list[dict]):
    """Save games list to games.json."""
    with open(GAMES_JSON, "w") as f:
        json.dump(games, f, indent=2, ensure_ascii=False)


def update_games(scraped: list[dict]) -> list[dict]:
    """Merge scraped games into games.json. Returns list of newly added games."""
    existing = load_games_json()
    existing_ids = {g["game_id"] for g in existing}

    new_games = [g for g in scraped if g["game_id"] not in existing_ids]
    if new_games:
        existing.extend(new_games)
        save_games_json(existing)

    return new_games
