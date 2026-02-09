# NBL Rotations - nbldata.cz

Vizualizace rotací hráčů v české basketbalové lize (NBL). Automaticky stahuje výsledky z [nbl.basketball](https://nbl.basketball), parsuje play-by-play data z FIBA LiveStats API a generuje interaktivní grafy rotací pro každý zápas. Vzorem mi byl web [www.nbarotations.info](https://nbarotations.info/). Názory a návrhy na vylepšení napište na opavak@gmail.com

## Co to umí

- **Scraping** dohrných zápasů z nbl.basketball (datum, týmy, skóre, livestats ID)
- **Rotační grafy** - po minutách zobrazují, kdo byl na hřišti, s barevným kódováním
- **Play-by-play analýza** z FIBA LiveStats API (střídání, střelba, fauly, ...)
- **Box score** z PBP dat (body, doskoky, asistence, bloky, ztráty, ...)
- **+/−** pro každého hráče i po minutách
- **Statický web** hostovaný na GitHub Pages

## Použití

```bash
# Aktivace virtualenv
source .venv/bin/activate

# Scraping nových zápasů z nbl.basketball
python main.py --scrape

# Scraping + generování HTML pro nové zápasy
python main.py --scrape --generate

# Přegenerování všech zápasů z games.json
python main.py --all

# Jeden konkrétní zápas podle FIBA LiveStats ID
python main.py --game-id 2803564
```

## Struktura

```
nbl_rotations/
  scraper.py      # scraping nbl.basketball
  fetcher.py      # stahování dat z FIBA LiveStats API + cache
  parser.py       # parsování PBP do datových struktur
  rotations.py    # výpočet rotací (stinty hráčů)
  ratings.py      # ORTG/DRTG metriky
  generator.py    # generování HTML + JSON pro vizualizaci
templates/        # Jinja2 šablony (index, detail zápasu)
static/           # CSS + D3.js vizualizace
docs/             # vygenerovaný statický web (GitHub Pages)
games.json        # databáze dohrných zápasů
```

## Závislosti

```
pip install -r requirements.txt
```

- `requests` - HTTP klient
- `jinja2` - šablony
- `beautifulsoup4` + `lxml` - HTML parsing pro scraper
