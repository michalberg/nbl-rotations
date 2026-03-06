# NBL Rotations - nbldata.cz

Vizualizace rotací hráčů a statistická analýza české basketbalové ligy (NBL). Automaticky stahuje výsledky z [nbl.basketball](https://nbl.basketball), parsuje play-by-play data z FIBA LiveStats API a generuje interaktivní grafy a statistiky. Vzorem mi byl web [www.nbarotations.info](https://nbarotations.info/). Názory a návrhy na vylepšení napište na opavak@gmail.com

## Co to umí

### Detail zápasu
- **Rotační grafy** – po minutách zobrazují, kdo byl na hřišti, s barevným kódováním
- **Box score** z PBP dat (body, doskoky, asistence, bloky, ztráty, …)
- **+/−** pro každého hráče i po minutách
- **Průběh skóre** – vizualizace vývoje skóre v čase
- **Herní situace** – body ze ztrát, z vymezeného území (paint), z druhých šancí, z rychlých protiútoků, z lavičky, největší vedení, nejdelší scoring run

### Statistiky hráčů
- Sezónní průměry a celkové hodnoty
- Leaderboard (TOP hráči v každé kategorii)
- **Forma** – trend výkonnosti v čase
- **Dvojice** – nejčastější přihrávkové dvojice (passer → scorer)
- **Nejlepší výkony** – sezónní rekordy hráče v každé statistice

### Statistiky týmů
- Sezónní průměry (základní, střelba, fauly a ztráty, soupeř, doubles, pokročilé)
- **Herní situace** – agregované situační statistiky napříč sezónou
- **Dvojice** – heatmapa a tabulka přihrávkových dvojic v týmu
- Pokročilé metriky: Pace, ORTG, DRTG, Net Rating

### TOP stránky
- **TOP zápasy** – rekordy zápasů (skóre, rozdíl, fauly, trojky, …)
- **TOP výkony** – ligové TOP 5 v každé kategorii + přehled triple doubles
- **Milníky** – hráči blízko kariérních milníků
- **Ratings** – on/off statistiky a lineup analýza

## Použití

```bash
# Aktivace virtualenv
source .venv/bin/activate

# Scraping nových zápasů z nbl.basketball
python main.py --scrape

# Scraping + generování HTML pro nové zápasy
python main.py --scrape --generate

# Přegenerování všeho z games.json
python main.py --all

# Jeden konkrétní zápas podle FIBA LiveStats ID
python main.py --game-id 2803564
```

## Struktura

```
nbl_rotations/
  scraper.py      # scraping nbl.basketball
  fetcher.py      # stahování dat z FIBA LiveStats API + cache
  parser.py       # parsování PBP do datových struktur (vč. qualifiers)
  rotations.py    # výpočet rotací (stinty hráčů)
  ratings.py      # ORTG/DRTG metriky
  stats.py        # sezónní log, agregace statistik
  generator.py    # generování HTML + JSON pro vizualizaci
templates/        # Jinja2 šablony
static/           # CSS + D3.js vizualizace
docs/             # vygenerovaný statický web (GitHub Pages)
games.json        # databáze dohrných zápasů
```

## Závislosti

```
pip install -r requirements.txt
```

- `requests` – HTTP klient
- `jinja2` – šablony
- `beautifulsoup4` + `lxml` – HTML parsing pro scraper
