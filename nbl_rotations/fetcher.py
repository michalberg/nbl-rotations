"""Download game data from FIBA LiveStats API with local caching."""

import json
import os
from pathlib import Path

import requests

LIVESTATS_URL = "https://www.fibalivestats.com/data/{game_id}/data.json"
CACHE_DIR = Path(__file__).parent.parent / "cache"


def fetch_game(game_id: str) -> dict:
    """Fetch game data, using cache if available."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = CACHE_DIR / f"{game_id}.json"

    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)

    url = LIVESTATS_URL.format(game_id=game_id)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    with open(cache_path, "w") as f:
        json.dump(data, f)

    return data


def load_game_ids(filepath: str) -> list[str]:
    """Read game IDs from a text file (one per line)."""
    ids = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                ids.append(line)
    return ids
