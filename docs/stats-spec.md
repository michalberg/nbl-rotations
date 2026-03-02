# NBL Stats – Specifikace výpočtů

## Player statistics

### Základní
- Games – počet zápasů
- Total minutes – celkové minuty
- Minutes per game

### Body
- Total points
- Points per game

### Doskoky
- Total rebounds
- Rebounds per game
- Offensive rebounds per game
- Defensive rebounds per game

### Další základní
- Total assists / Assists per game
- Total steals / Steals per game
- Total blocks / Blocks per game
- Turnovers / Turnovers per game
- Personal fouls / Personal fouls per game
- Personal fouls drawn / Personal fouls drawn per game

### Střelba
- Field Goal % = FGM / FGA
- Field Goals made / attempts / missed
- 2-Pt FG% / made / attempts / missed / per game
- 3-Pt FG% / made / attempts / missed / per game
- Free throw % = FTM / FTA
- Free throws attempts (total + per game)
- Free throws made (total + per game)

### Pokročilé metriky
- Usage% = (FGA + 0.44×FTA + TOV) / (TeamFGA + 0.44×TeamFTA + TeamTOV) × 100
- PER (Player Efficiency Rating) – zjednodušená verze bez ligové normalizace:
  PER = (PTS + REB + AST + STL + BLK - (FGA - FGM) - (FTA - FTM) - TOV) / GP
- True Shooting% = PTS / (2 × (FGA + 0.44 × FTA))
- eFG% = (FGM + 0.5 × 3PM) / FGA
- Plus/Minus (per game i sezóna)

### Milníky
- Double-doubles (+ seznam zápasů)
- Triple-doubles (+ seznam zápasů)
- Fouls-out (5 faulů v zápase)
- Technicals

### Best game rekordy
- Best game: points, assists, rebounds, offensive rebounds, defensive rebounds,
  blocks, steals, FGM, FGA, 2PM, 2PA, 3PM, 3PA, FTM, FTA, minutes
  (hodnota + odkaz na zápas)

---

## Team statistics

### Základní
- Points scored / per game
- Total rebounds / per game / OREB per game / DREB per game
- Assists / per game
- Steals / per game
- Blocks / per game
- Turnovers / per game
- Personal fouls / per game
- Personal fouls drawn / per game

### Střelba
- FG% / FGM / FGA / missed
- 2-Pt FG% / made / attempts / missed / per game
- 3-Pt FG% / made / attempts / missed / per game
- FT% / FTA total + per game / FTM total + per game

### Soupeř (Opponent stats) – stejné kategorie jako tým:
- Opponent points, FG%, FGM, FGA, 3P%, 3PM, 3PA, FT%, FTM, FTA
- Opponent rebounds (total, OREB, DREB)
- Opponent assists, fouls, steals, blocks, turnovers

### Pokročilé metriky
- Team_POSS = FGA + 0.44×FTA - 1.07×(OREB/(OREB+Opp_DREB))×FGA + TOV
- Opp_POSS = Opp_FGA + 0.44×Opp_FTA - 1.07×(Opp_OREB/(Opp_OREB+DREB))×Opp_FGA + Opp_TOV
- Pace = 40 × ((Team_POSS + Opp_POSS) / 2) / Minutes_Played
- ORTG = (Points / Team_POSS) × 100
- DRTG = (Points Allowed / Opp_POSS) × 100
- Net RTG = ORTG - DRTG

---

## Games rekordy

- Největší rozdíl skóre
- Nejvíce bodů celkem / nejméně bodů celkem
- Největší obrat (biggest comeback)
- Nejvíce faulů jedním týmem / oběma týmy
- Nejvíce / nejméně trestných hodů pokusů (1 tým / oba)
- Nejvíce / nejméně trestných hodů proměněných (1 tým / oba)
- Nejvíce trestných hodů neproměněných (1 tým / oba)
- Nejvíce trojkových pokusů (1 tým / oba)
- Nejvíce proměněných trojek (1 tým / oba)
- Nejvíce neproměněných trojek (1 tým / oba)
- Nejlepší % trojek (1 tým / oba)
- Nejhorší % trojek (1 tým / oba)
