"""
Base de datos de partidas de Ranked Solo/Duo y winrate contra campeones rivales.

Al iniciar, el programa pide el Riot ID del jugador (Nombre#TAG).

Uso:
  python lol_db.py                   descarga las partidas nuevas y muestra los matchups
  python lol_db.py --sin-descargar   solo analiza lo que ya está guardado (no usa la API)
  python lol_db.py --con Ahri        matchups solo de las partidas en que jugó Ahri
  python lol_db.py --min 5           oculta rivales con menos de 5 partidas
  python lol_db.py --partidas 200    analiza/descarga otra cantidad de partidas
  python lol_db.py --jugador "Nombre#TAG"   no pregunta el jugador al inicio
  python lol_db.py --sin-abrir       genera el dashboard HTML sin abrirlo en el navegador
  python lol_db.py --last-match      resumen completo de tu última partida de Ranked Solo

Al terminar genera reportes/<Nombre>.html (necesita dashboard.py en la misma carpeta).
Con --last-match genera reportes/<Nombre>_ultima_partida.html (necesita ultima_partida.py).

Requiere:  la librería requests (si falta, el programa ofrece instalarla con pip)
           y tu API key de Riot en el archivo .env (RIOT_API_KEY=RGAPI-...), junto a este script.
Cada jugador tiene su base de datos en bases_de_datos/<Nombre>.db, y sus tablas
en CSV en reportes/. Si cortas la descarga (Ctrl+C), lo descargado queda guardado
y se retoma desde ahí la próxima vez.
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path


def ensure_requests():
    """Importa requests; si falta, ofrece instalarlo con pip para este mismo Python."""
    try:
        import requests
        return requests
    except ImportError:
        pass
    print("Falta la librería 'requests', necesaria para usar la API de Riot.")
    try:
        answer = input("¿Instalarla ahora con pip? [S/n]: ").strip().lower()
    except EOFError:
        answer = "n"
    if answer not in ("", "s", "si", "sí", "y", "yes"):
        sys.exit(f"Instálala con:  \"{sys.executable}\" -m pip install requests")

    import importlib
    import subprocess
    if subprocess.call([sys.executable, "-m", "pip", "install", "requests"]) != 0:
        sys.exit("\nNo se pudo instalar con pip.\n"
                 f"  - Si dice 'No module named pip':  \"{sys.executable}\" -m ensurepip\n"
                 "  - Si dice 'externally-managed-environment' (Linux), usa un entorno virtual:\n"
                 "      python -m venv .venv  y corre el programa con .venv/bin/python")
    importlib.invalidate_caches()
    import requests
    print()
    return requests


requests = ensure_requests()

# ───────────── CONFIGURACIÓN ─────────────
TAG_POR_DEFECTO = "LAN"    # se usa si escribes el nombre sin #TAG y das Enter al pedir el tag
REGION = "americas"        # americas (LAN, LAS, NA, BR) / europe / asia
PARTIDAS = 400             # cuántas partidas de Ranked Solo descargar y analizar
MIN_PARTIDAS = 3           # mínimo de partidas contra un rival para mostrarlo
PAUSA = 1.25               # segundos entre peticiones (la key de desarrollo permite ~100 cada 2 min)
# ─────────────────────────────────────────

QUEUE_SOLO = 420
BASE = Path(__file__).resolve().parent
DB_DIR = BASE / "bases_de_datos"
REPORT_DIR = BASE / "reportes"
ROLES = {"TOP": "Top", "JUNGLE": "Jungla", "MIDDLE": "Mid", "BOTTOM": "ADC", "UTILITY": "Support"}


def load_api_key():
    """Lee RIOT_API_KEY del archivo .env junto a este script.
    Si la variable de entorno RIOT_API_KEY existe, tiene prioridad."""
    if os.environ.get("RIOT_API_KEY"):
        return os.environ["RIOT_API_KEY"].strip()
    env = BASE / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "RIOT_API_KEY":
                return value.strip().strip("\"'")
    return ""


API_KEY = load_api_key()   # genera una en developer.riotgames.com

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS matches (
    match_id   TEXT PRIMARY KEY,
    game_start INTEGER,          -- milisegundos desde 1970
    duration   INTEGER,          -- segundos
    patch      TEXT,
    queue_id   INTEGER,
    remake     INTEGER,          -- 1 si fue remake (se excluye de las stats)
    raw        TEXT              -- JSON completo de Riot, por si quieres más datos después
);
CREATE TABLE IF NOT EXISTS participants (
    match_id    TEXT,
    puuid       TEXT,
    riot_id     TEXT,
    team_id     INTEGER,
    champion_id INTEGER,
    champion    TEXT,
    position    TEXT,
    win         INTEGER,
    kills INTEGER, deaths INTEGER, assists INTEGER,
    cs INTEGER, gold INTEGER, damage INTEGER, vision INTEGER,
    PRIMARY KEY (match_id, puuid)
);
CREATE INDEX IF NOT EXISTS idx_participants_puuid ON participants(puuid);
CREATE TABLE IF NOT EXISTS timelines (
    match_id TEXT PRIMARY KEY,
    raw      TEXT                -- JSON del timeline de Riot (oro por minuto, eventos, compras)
);
"""


# ─────────────────── API ───────────────────
_last_call = 0.0


def get(url, params=None):
    """GET a la API de Riot con pausa entre llamadas y reintento en 429.
    Devuelve None si el recurso no existe (404)."""
    global _last_call
    while True:
        wait = PAUSA - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        try:
            r = requests.get(url, headers={"X-Riot-Token": API_KEY}, params=params, timeout=20)
        except requests.RequestException as e:
            print(f"\n  Error de conexión ({e.__class__.__name__}), reintentando en 5s...")
            time.sleep(5)
            continue
        if r.status_code == 429:
            retry = int(r.headers.get("Retry-After", 10))
            print(f"\n  Límite de peticiones alcanzado, esperando {retry}s...")
            time.sleep(retry)
            continue
        if r.status_code >= 500:
            print(f"\n  Riot respondió {r.status_code}, reintentando en 5s...")
            time.sleep(5)
            continue
        if r.status_code in (401, 403):
            sys.exit("\nError: la API key es inválida o expiró. "
                     "Genera una nueva en developer.riotgames.com y actualiza el archivo .env")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


def champion_names():
    """Mapa id numérico -> nombre del campeón, desde Data Dragon."""
    try:
        version = requests.get(
            "https://ddragon.leagueoflegends.com/api/versions.json", timeout=15).json()[0]
        data = requests.get(
            f"https://ddragon.leagueoflegends.com/cdn/{version}/data/es_MX/champion.json",
            timeout=15).json()["data"]
        return {int(c["key"]): c["name"] for c in data.values()}
    except Exception:
        print("  Aviso: no se pudieron cargar los nombres de Data Dragon; se usarán los internos.")
        return {}


# ─────────────── Base de datos ───────────────
def safe_filename(name):
    """Quita caracteres que Windows no permite en nombres de archivo."""
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(".")
    if not clean or clean.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                      *(f"LPT{i}" for i in range(1, 10))}:
        clean += "_"
    return clean


def stored_riot_id(path):
    """Riot ID guardado dentro de una base existente, o None."""
    try:
        conn = sqlite3.connect(path)
        row = conn.execute("SELECT value FROM meta WHERE key='riot_id'").fetchone()
        conn.close()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def db_path_for(name, tag):
    """bases_de_datos/<Nombre>.db. Si ese archivo ya pertenece a otra cuenta con el
    mismo nombre y distinto tag, usa <Nombre>_<TAG>.db para no mezclarlas."""
    DB_DIR.mkdir(exist_ok=True)
    path = DB_DIR / f"{safe_filename(name)}.db"
    owner = stored_riot_id(path) if path.exists() else None
    if owner and owner.lower() != f"{name}#{tag}".lower():
        alt = DB_DIR / f"{safe_filename(name)}_{safe_filename(tag)}.db"
        print(f"  Aviso: {path.name} ya es de {owner}; esta cuenta se guarda en {alt.name}")
        return alt
    return path


def find_existing_db(name, tag):
    """Busca la base ya creada de esta cuenta, sin importar mayúsculas."""
    wanted = f"{name}#{tag}".lower()
    if DB_DIR.exists():
        for path in sorted(DB_DIR.glob("*.db")):
            owner = stored_riot_id(path)
            if owner and owner.lower() == wanted:
                return path
    return None


def open_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def ask_player(arg):
    """Pide el Riot ID al usuario (o usa --jugador). Devuelve (nombre, tag)."""
    text = arg
    while not text:
        text = input("Jugador a buscar (Nombre#TAG): ").strip()
    if "#" in text:
        name, tag = text.rsplit("#", 1)
    else:
        name = text
        tag = "" if arg else input(f"Tag (Enter = {TAG_POR_DEFECTO}): ").strip()
    name, tag = name.strip(), tag.strip().lstrip("#") or TAG_POR_DEFECTO
    if not name:
        sys.exit("El nombre del jugador no puede estar vacío.")
    return name, tag


def save_match(conn, data, names):
    info = data["info"]
    match_id = data["metadata"]["matchId"]
    parts = info["participants"]
    remake = int(info["gameDuration"] < 300
                 or any(p.get("gameEndedInEarlySurrender") for p in parts))
    patch = ".".join(str(info.get("gameVersion", "")).split(".")[:2])

    conn.execute(
        "INSERT OR REPLACE INTO matches VALUES (?,?,?,?,?,?,?)",
        (match_id, info["gameCreation"], info["gameDuration"], patch,
         info["queueId"], remake, json.dumps(data, separators=(",", ":"))))
    conn.executemany(
        "INSERT OR REPLACE INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(match_id, p["puuid"],
          f"{p.get('riotIdGameName', '')}#{p.get('riotIdTagline', '')}",
          p["teamId"], p["championId"],
          names.get(p["championId"], p["championName"]),
          p.get("teamPosition") or "",
          int(p["win"]), p["kills"], p["deaths"], p["assists"],
          p["totalMinionsKilled"] + p["neutralMinionsKilled"],
          p["goldEarned"], p["totalDamageDealtToChampions"], p["visionScore"])
         for p in parts])


def download(conn, puuid, total):
    names = champion_names()
    base = f"https://{REGION}.api.riotgames.com/lol/match/v5/matches"

    print(f"Buscando tus últimas {total} partidas de Ranked Solo...")
    ids, start = [], 0
    while len(ids) < total:
        count = min(100, total - len(ids))
        batch = get(f"{base}/by-puuid/{puuid}/ids",
                    {"queue": QUEUE_SOLO, "type": "ranked", "start": start, "count": count})
        if not batch:
            break
        ids += batch
        start += len(batch)
        if len(batch) < count:
            break

    saved = {row[0] for row in conn.execute("SELECT match_id FROM matches")}
    new = [i for i in ids if i not in saved]
    print(f"  Encontradas: {len(ids)}  |  Ya guardadas: {len(ids) - len(new)}  |  Por descargar: {len(new)}")
    if not new:
        return
    print(f"  Tiempo estimado: ~{len(new) * PAUSA / 60:.0f} min (puedes cortar con Ctrl+C y retomar después)")

    for n, match_id in enumerate(new, 1):
        data = get(f"{base}/{match_id}")
        if data is not None:
            save_match(conn, data, names)
            conn.commit()
        print(f"\r  Descargando {n}/{len(new)}  ({match_id})   ", end="", flush=True)
    print("\n  Descarga completa.")


def fetch_last_match(conn, puuid):
    """Descarga solo la última partida de Ranked Solo y su timeline, si faltan."""
    base = f"https://{REGION}.api.riotgames.com/lol/match/v5/matches"
    print("Buscando tu última partida de Ranked Solo...")
    ids = get(f"{base}/by-puuid/{puuid}/ids", {"queue": QUEUE_SOLO, "type": "ranked", "start": 0, "count": 1})
    if not ids:
        return
    match_id = ids[0]
    if not conn.execute("SELECT 1 FROM matches WHERE match_id = ?", (match_id,)).fetchone():
        print(f"  Descargando {match_id}...")
        data = get(f"{base}/{match_id}")
        if data is None:
            return
        save_match(conn, data, champion_names())
        conn.commit()
    if not conn.execute("SELECT 1 FROM timelines WHERE match_id = ?", (match_id,)).fetchone():
        print("  Descargando la línea de tiempo...")
        tl = get(f"{base}/{match_id}/timeline")
        if tl is not None:
            conn.execute("INSERT OR REPLACE INTO timelines VALUES (?,?)",
                         (match_id, json.dumps(tl, separators=(",", ":"))))
            conn.commit()


# ─────────────── Análisis ───────────────
MINE = """
WITH mine AS (
    SELECT p.* FROM participants p JOIN matches m USING (match_id)
    WHERE p.puuid = :me AND m.remake = 0 AND m.queue_id = 420
    ORDER BY m.game_start DESC
    LIMIT :n
)
"""


def matchup_query(lane_only):
    lane = "AND o.position = mine.position AND mine.position <> ''" if lane_only else ""
    return MINE + f"""
SELECT o.champion,
       COUNT(*)                   AS games,
       SUM(mine.win)              AS wins,
       SUM(mine.kills), SUM(mine.deaths), SUM(mine.assists),
       AVG(mine.gold - o.gold)    AS gold_diff
FROM mine
JOIN participants o
  ON o.match_id = mine.match_id AND o.team_id <> mine.team_id {lane}
WHERE (:con IS NULL OR LOWER(mine.champion) = LOWER(:con))
GROUP BY o.champion
"""


def table(headers, rows, align):
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h))
              for i, h in enumerate(headers)]
    line = "  ".join(f"{h:{a}{w}}" for h, a, w in zip(headers, align, widths))
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(f"{str(c):{a}{w}}" for c, a, w in zip(r, align, widths)))


def title(text):
    print(f"\n{'=' * 70}\n  {text}\n{'=' * 70}")


def build_rows(raw, with_gold):
    rows = []
    for champ, g, w, k, d, a, gold in raw:
        row = {"Rival": champ, "Partidas": g, "Victorias": w, "Derrotas": g - w,
               "Winrate": round(100 * w / g, 1), "KDA": round((k + a) / max(1, d), 2)}
        if with_gold:
            row["Dif. oro prom."] = round(gold)
        rows.append(row)
    rows.sort(key=lambda r: (-r["Partidas"], -r["Winrate"]))
    return rows


def show(rows, min_games, with_gold, label):
    visible = [r for r in rows if r["Partidas"] >= min_games]
    headers = ["Rival", "Partidas", "V-D", "Winrate", "Tu KDA"] + (["Dif. oro"] if with_gold else [])
    align = ["<", ">", ">", ">", ">"] + ([">"] if with_gold else [])
    out = []
    for r in visible:
        line = [r["Rival"], r["Partidas"], f"{r['Victorias']}-{r['Derrotas']}",
                f"{r['Winrate']:.0f}%", f"{r['KDA']:.2f}"]
        if with_gold:
            line.append(f"{r['Dif. oro prom.']:+,}")
        out.append(line)
    table(headers, out, align)
    hidden = len(rows) - len(visible)
    if hidden:
        print(f"\n  ({hidden} {label} con menos de {min_games} partidas no se muestran; están en el CSV)")

    ranked = [r for r in visible if r["Partidas"] >= max(min_games, 5)]
    if len(ranked) >= 6:
        worst = sorted(ranked, key=lambda r: (r["Winrate"], -r["Partidas"]))[:5]
        best = sorted(ranked, key=lambda r: (-r["Winrate"], -r["Partidas"]))[:5]
        print(f"\n  Más difíciles (5+ partidas): " +
              ", ".join(f"{r['Rival']} {r['Winrate']:.0f}% ({r['Partidas']})" for r in worst))
        print(f"  Más fáciles   (5+ partidas): " +
              ", ".join(f"{r['Rival']} {r['Winrate']:.0f}% ({r['Partidas']})" for r in best))


def export_csv(rows, filename):
    if not rows:
        return
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / filename
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def analyze(conn, puuid, total, min_games, con, file_prefix):
    params = {"me": puuid, "n": total, "con": con}
    summary = conn.execute(MINE + """
        SELECT COUNT(*), SUM(win), MIN(m.game_start), MAX(m.game_start)
        FROM mine JOIN matches m USING (match_id)
        WHERE (:con IS NULL OR LOWER(mine.champion) = LOWER(:con))""", params).fetchone()
    games, wins, first, last = summary
    if not games:
        print("\nNo hay partidas para analizar" + (f" con {con}." if con else "."))
        return

    fmt = lambda ms: datetime.fromtimestamp(ms / 1000).strftime("%d/%m/%Y")
    who = conn.execute("SELECT value FROM meta WHERE key='riot_id'").fetchone()
    title(f"{who[0] if who else ''}  |  Ranked Solo" + (f"  |  jugando {con}" if con else ""))
    print(f"  Partidas analizadas: {games}  (sin remakes)  |  {fmt(first)} a {fmt(last)}")
    print(f"  Récord: {wins}V - {games - wins}D  |  Winrate general: {100 * wins / games:.1f}%")

    roles = conn.execute(MINE + """
        SELECT position, COUNT(*), SUM(win) FROM mine
        WHERE (:con IS NULL OR LOWER(champion) = LOWER(:con))
        GROUP BY position ORDER BY COUNT(*) DESC""", params).fetchall()
    print("  Por rol: " + "  |  ".join(
        f"{ROLES.get(p, p or '?')} {g} ({100 * w / g:.0f}%)" for p, g, w in roles))

    lane = build_rows(conn.execute(matchup_query(True), params).fetchall(), True)
    title("CONTRA TU RIVAL DE LÍNEA")
    print("  Dif. oro = tu oro al final menos el de tu rival, en promedio.\n")
    show(lane, min_games, True, "rivales")

    team = build_rows(conn.execute(matchup_query(False), params).fetchall(), False)
    title("CON CADA CAMPEÓN EN EL EQUIPO ENEMIGO (cualquier rol)")
    show(team, min_games, False, "campeones")

    suffix = f"_{safe_filename(con.lower())}" if con else ""
    p1 = export_csv(lane, f"{file_prefix}_matchups_linea{suffix}.csv")
    p2 = export_csv(team, f"{file_prefix}_matchups_equipo{suffix}.csv")
    print(f"\nTablas completas guardadas en:\n  {p1}\n  {p2}")
    print("\nOjo: con menos de ~10 partidas, un winrate dice poco. "
          "Fíjate en la columna Partidas antes de sacar conclusiones.")


def show_last_match(data):
    me = next(p for p in data["players"] if p["me"])
    m = data["match"]
    result = "REMAKE" if m["remake"] else "VICTORIA" if m["win"] else "DERROTA"
    title(f"{result}  |  {me['c']} {me['k']}/{me['d']}/{me['a']}  |  {m['d'] // 60}:{m['d'] % 60:02d}")
    when = datetime.fromtimestamp(m["t"] / 1000).strftime("%d/%m/%Y %H:%M")
    rival = next((p for p in data["players"] if p["id"] == data["rival"]), None)
    print(f"  {when}  |  Parche {m['patch']}  |  {ROLES.get(me['pos'], me['pos'] or '?')}"
          + (f"  |  contra {rival['c']}" if rival else ""))
    if data["badges"]:
        print("  " + "  ·  ".join(data["badges"]))

    print()
    for label, value, sub in data["tiles"]:
        print(f"  {label + ':':<18} {value:>8}   {sub}")

    for team in (me["team"], 300 - me["team"]):
        t = data["teams"][team]
        title(("TU EQUIPO" if team == me["team"] else "EQUIPO ENEMIGO") + f"  ·  {'Victoria' if t['win'] else 'Derrota'}")
        table(["", "Campeón", "Jugador", "K/D/A", "CS", "Oro", "Daño"],
              [["»" if p["me"] else "", p["c"], p["name"], f"{p['k']}/{p['d']}/{p['a']}",
                p["cs"], f"{p['gold']:,}", f"{p['dmg']:,}"]
               for p in data["players"] if p["team"] == team],
              ["<", "<", "<", ">", ">", ">", ">"])
        o = t["obj"]
        print(f"\n  Torres {o.get('tower', 0)}  ·  Dragones {o.get('dragon', 0)}  ·  Larvas {o.get('horde', 0)}"
              f"  ·  Heraldo {o.get('riftHerald', 0)}  ·  Barón {o.get('baron', 0)}"
              f"  ·  Inhibidores {o.get('inhibitor', 0)}")

    if data["lane"]:
        title(f"TÚ VS {rival['c'].upper()}")
        table(["", "Tú", rival["c"], "Dif."],
              [[r["l"], f"{r['a']:,}", f"{r['b']:,}", f"{r['a'] - r['b']:+,}"] for r in data["lane"]],
              ["<", ">", ">", ">"])
    if not data["tl"]:
        print("\n  (Sin línea de tiempo: corre sin --sin-descargar para tener oro por minuto, build y eventos.)")


def last_match(conn, puuid, stem, open_browser):
    row = conn.execute("""
        SELECT m.match_id, m.raw FROM matches m JOIN participants p USING (match_id)
        WHERE p.puuid = ? AND m.queue_id = 420 ORDER BY m.game_start DESC LIMIT 1""", (puuid,)).fetchone()
    if not row:
        print("\nNo hay partidas guardadas para resumir.")
        return
    try:
        import ultima_partida
    except ImportError:
        sys.exit("Para --last-match, guarda ultima_partida.py en la misma carpeta que este script.")
    tl = conn.execute("SELECT raw FROM timelines WHERE match_id = ?", (row[0],)).fetchone()
    data = ultima_partida.build(json.loads(row[1]), json.loads(tl[0]) if tl else None, puuid)
    show_last_match(data)
    html = ultima_partida.generate(data, REPORT_DIR / f"{stem}_ultima_partida.html")
    print(f"\nResumen: {html}")
    if open_browser:
        import webbrowser
        webbrowser.open(html.resolve().as_uri())


# ─────────────── Principal ───────────────
def main():
    ap = argparse.ArgumentParser(description="Tus matchups de Ranked Solo")
    ap.add_argument("--sin-descargar", action="store_true", help="no usar la API, solo analizar")
    ap.add_argument("--partidas", type=int, default=PARTIDAS)
    ap.add_argument("--min", type=int, default=MIN_PARTIDAS)
    ap.add_argument("--con", default=None, help="filtrar por el campeón que jugó")
    ap.add_argument("--jugador", default=None, help='Riot ID, ej. "Nombre#TAG" (si no, lo pregunta)')
    ap.add_argument("--sin-abrir", action="store_true", help="no abrir el dashboard en el navegador")
    ap.add_argument("--last-match", "--ultima-partida", action="store_true", dest="last_match",
                    help="resumen completo de la última partida de Ranked Solo")
    args = ap.parse_args()

    if not args.sin_descargar and not API_KEY:
        sys.exit("Falta la API key de Riot. Genera una en developer.riotgames.com y guárdala en "
                 f"{BASE / '.env'} así:\n  RIOT_API_KEY=RGAPI-...\n(o usa --sin-descargar).")
    name, tag = ask_player(args.jugador)

    if args.sin_descargar:
        path = find_existing_db(name, tag)
        if path is None:
            sys.exit(f"No hay base de datos para {name}#{tag} en {DB_DIR.name}/. "
                     "Corre primero sin --sin-descargar.")
        conn = open_db(path)
        row = conn.execute("SELECT value FROM meta WHERE key='puuid'").fetchone()
        if not row:
            sys.exit(f"{path.name} está vacía. Corre primero sin --sin-descargar.")
        puuid = row[0]
    else:
        acc = get(f"https://{REGION}.api.riotgames.com/riot/account/v1/accounts/"
                  f"by-riot-id/{requests.utils.quote(name)}/{requests.utils.quote(tag)}")
        if acc is None:
            sys.exit(f"No se encontró la cuenta {name}#{tag}. Revisa el nombre, tag y región.")
        puuid = acc["puuid"]
        # Usa el nombre y tag exactos de Riot (mayúsculas, acentos) para el archivo.
        name, tag = acc["gameName"], acc["tagLine"]
        path = db_path_for(name, tag)
        conn = open_db(path)
        conn.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)",
                         [("puuid", puuid), ("riot_id", f"{name}#{tag}")])
        conn.commit()
        print(f"Base de datos: {path}")
        try:
            if args.last_match:
                fetch_last_match(conn, puuid)
            else:
                download(conn, puuid, args.partidas)
        except KeyboardInterrupt:
            print("\n  Descarga interrumpida. Lo descargado quedó guardado; analizando eso...")

    if args.last_match:
        last_match(conn, puuid, path.stem, not args.sin_abrir)
        conn.close()
        return

    analyze(conn, puuid, args.partidas, args.min, args.con, path.stem)

    try:
        import dashboard
    except ImportError:
        print("\n(Para el dashboard HTML, guarda dashboard.py en la misma carpeta que este script.)")
    else:
        html = dashboard.generate(conn, puuid, args.partidas, REPORT_DIR / f"{path.stem}.html")
        print(f"\nDashboard: {html}")
        if not args.sin_abrir:
            import webbrowser
            webbrowser.open(html.resolve().as_uri())
    conn.close()


if __name__ == "__main__":
    main()