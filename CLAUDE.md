# NBL Rotations

Parser play-by-play dat z FIBA LiveStats API + webová vizualizace rotací pro českou NBL.

## Stack

- **Python**: stahování dat, parsování PBP, výpočet rotací a ratingů, generování statických HTML
- **D3.js**: interaktivní vizualizace rotačních grafů
- **GitHub Pages**: hosting (adresář `docs/`)

## Usage

```bash
source .venv/bin/activate

python main.py --scrape                # scrapne nbl.basketball, uloží do games.json
python main.py --scrape --generate     # scrapne + vygeneruje HTML pro nové zápasy
python main.py --all                   # přegeneruje vše z games.json
python main.py --game-id 2803564       # jeden konkrétní zápas
python main.py --fetch-only games.txt  # jen stažení dat do cache
```

## Venv

Python 3.12 via `.venv/` (nikoli systémový python3 který je 3.5).

```bash
.venv/bin/python main.py --scrape --generate
```
