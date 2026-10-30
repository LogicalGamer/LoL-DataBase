# LoL DataBase

Downloads a player's League of Legends **Ranked Solo/Duo** games from the Riot API,
stores them in a local SQLite database, and shows how they do against every
champion they face. Each run produces console tables, CSV files and an HTML report.

The program's messages and reports are in Spanish.

## Features

- **Matchup analysis**: win rate, KDA and average gold difference against your lane
  opponent, plus win rate against every champion on the enemy team.
- **Incremental downloads**: only games that aren't already in the database are
  downloaded. If you stop a download with Ctrl+C, everything downloaded so far is
  kept and the next run continues from there.
- **One database per player**: `bases_de_datos/<Name>.db`. Each database keeps the
  full JSON Riot returns for every game, so you can pull more stats from it later.
- **HTML dashboard**: an interactive page with a champion filter, your hardest
  matchups, your stats, recent games, a sortable matchup table and the people you
  play with most.
- **Last-match summary** (`--last-match`): a full breakdown of your latest game,
  covering:
  - your stats and you vs your lane opponent at minutes 10 and 15
  - a minute-by-minute gold difference chart and objectives for both teams
  - the full scoreboard, your build order, skill order and runes
  - a timeline of key moments

## Requirements

- Python 3.10 or newer
- [`requests`](https://pypi.org/project/requests/)
- A Riot API key from <https://developer.riotgames.com>

## Setup

```bash
python -m venv .venv
source .venv/bin/activate            # fish: source .venv/bin/activate.fish
                                     # Windows: .venv\Scripts\activate
pip install requests
```

Put your API key in a `.env` file next to `Lol_db.py`. Start by copying the example
file:

```bash
cp .env.example .env                 # Windows: copy .env.example .env
```

Then edit `.env`:

```
RIOT_API_KEY=RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

`.env` is listed in `.gitignore`, so your key is never committed. If the
`RIOT_API_KEY` environment variable is set, it takes priority over the file.

> Development keys expire every 24 hours. If the program stops with
> *"la API key es inválida o expiró"*, generate a new key and replace it in `.env`.

## Usage

```bash
python Lol_db.py
```

The program asks for a Riot ID (`Name#TAG`). If you leave out the tag, it uses
`LAN`.

| Option | Description |
|---|---|
| `--jugador "Name#TAG"` | Use this player instead of asking |
| `--sin-descargar` | Don't call the API; analyse only what's already stored |
| `--partidas N` | Number of games to download and analyse (default 400) |
| `--con <Champion>` | Only games where you played that champion |
| `--min N` | Hide opponents you've faced fewer than N times (default 3) |
| `--sin-abrir` | Generate the HTML without opening it in the browser |
| `--last-match`, `--ultima-partida` | Summarise only the latest Ranked Solo game |

Examples:

```bash
python Lol_db.py --jugador "Luisdoom#UwU"
python Lol_db.py --jugador "Luisdoom#UwU" --con Gnar --min 5
python Lol_db.py --jugador "Luisdoom#UwU" --sin-descargar
python Lol_db.py --jugador "Luisdoom#UwU" --last-match
```

`--last-match` downloads only the latest game and its timeline, so it finishes in
seconds. Any games it skips are picked up the next time you run without it. When
used with `--sin-descargar`, a game whose timeline was never downloaded is still
summarised, but without the gold chart, build order or key moments.

## Output

```
bases_de_datos/
  <Name>.db                         SQLite database for each player
reportes/
  <Name>.html                       main dashboard
  <Name>_matchups_linea.csv         stats against your lane opponent
  <Name>_matchups_equipo.csv        stats against every enemy champion
  <Name>_ultima_partida.html        last-match summary (--last-match)
```

When you use `--con`, the champion's name is added to the end of the CSV file names.

If two accounts share a name but have different tags, the second one is saved as
`<Name>_<TAG>.db` so their data doesn't mix.

## Configuration

These constants are at the top of `Lol_db.py`:

| Constant | Default | Meaning |
|---|---|---|
| `REGION` | `americas` | Routing region: `americas` (LAN, LAS, NA, BR), `europe` or `asia` |
| `TAG_POR_DEFECTO` | `LAN` | Tag used when you leave it out of the Riot ID |
| `PARTIDAS` | `400` | Default number of games |
| `MIN_PARTIDAS` | `3` | Default minimum games against an opponent before it's shown |
| `PAUSA` | `1.25` | Seconds between requests (development keys allow about 100 every 2 minutes) |

## Project structure

| File | Purpose |
|---|---|
| `Lol_db.py` | Entry point: options, Riot API client, SQLite storage, console analysis, CSV export |
| `.env.example` | Template for `.env`, the file that holds your Riot API key (not committed) |
| `dashboard.py` | Builds the main HTML dashboard (`generate(conn, puuid, total, path)`) |
| `ultima_partida.py` | Builds the last-match summary (`build(match, timeline, puuid)`, `generate(data, path)`) |

Keep all three files in the same folder. `dashboard.py` and `ultima_partida.py` are
imported by `Lol_db.py`.

### Database schema

| Table | Contents |
|---|---|
| `meta` | `puuid` and `riot_id` of the account that owns the database |
| `matches` | One row per game: start time, length, patch, queue, remake flag, full Riot JSON |
| `participants` | One row per player per game: champion, role, team, result, K/D/A, CS, gold, damage, vision |
| `timelines` | The Riot timeline for a game (used by `--last-match`) |

Remakes (games under 5 minutes or ended by an early surrender) are stored but left
out of the stats.

## Notes

- Win rates over fewer than about 10 games don't tell you much, so check the
  number of games before drawing conclusions.
- Champion, item, rune and summoner spell names and images come from
  [Data Dragon](https://developer.riotgames.com/docs/lol#data-dragon), Riot's public
  data service. You need an internet connection to see the images in the HTML
  reports.

*LoL DataBase isn't endorsed by Riot Games and doesn't reflect the views or opinions
of Riot Games or anyone officially involved in producing or managing Riot Games
properties. Riot Games and League of Legends are trademarks or registered
trademarks of Riot Games, Inc.*
