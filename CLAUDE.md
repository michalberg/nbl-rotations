# NBL Rotations

Parser play-by-play dat z FIBA LiveStats API + webová vizualizace rotací pro českou NBL.

## Stack

- **Python**: stahování dat, parsování PBP, výpočet rotací a ratingů, generování statických HTML
- **D3.js**: interaktivní vizualizace rotačních grafů
- **GitHub Pages**: hosting (adresář `docs/`)

## Usage

```bash
python main.py games.txt              # stáhne, parsuje, vygeneruje HTML
python main.py --game-id 2803564      # jeden konkrétní zápas
python main.py --fetch-only games.txt # jen stažení dat
```
