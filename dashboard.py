"""
Genera un dashboard HTML a partir de la base de datos de un jugador.
Lo usa lol_db.py; guarda este archivo en la misma carpeta.
"""
import json
from collections import defaultdict
from datetime import datetime

import requests


def ddragon_ids():
    """(versión, {id numérico: id de Data Dragon}) para armar URLs de imágenes."""
    try:
        version = requests.get(
            "https://ddragon.leagueoflegends.com/api/versions.json", timeout=15).json()[0]
        data = requests.get(
            f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json",
            timeout=15).json()["data"]
        return version, {int(c["key"]): c["id"] for c in data.values()}
    except Exception:
        return None, {}


def build_data(conn, puuid, total):
    rows = conn.execute("""
        SELECT p.match_id, m.game_start, m.duration, p.team_id, p.champion, p.champion_id,
               p.position, p.win, p.kills, p.deaths, p.assists, p.cs, p.gold
        FROM participants p JOIN matches m USING (match_id)
        WHERE p.puuid = ? AND m.remake = 0 AND m.queue_id = 420
        ORDER BY m.game_start DESC LIMIT ?""", (puuid, total)).fetchall()

    ids = [r[0] for r in rows]
    others = defaultdict(list)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        marks = ",".join("?" * len(chunk))
        for o in conn.execute(f"""
                SELECT match_id, riot_id, team_id, champion, champion_id, position, gold
                FROM participants WHERE match_id IN ({marks}) AND puuid <> ?""",
                              (*chunk, puuid)):
            others[o[0]].append(o)

    version, keymap = ddragon_ids()
    dd = {}

    def register(name, cid):
        if cid in keymap:
            dd[name] = keymap[cid]

    games = []
    mates = defaultdict(lambda: [0, 0])
    for mid, t, dur, team, champ, cid, pos, win, k, d, a, cs, gold in rows:
        register(champ, cid)
        rival, enemies = None, []
        for _, riot_id, o_team, o_champ, o_cid, o_pos, o_gold in others[mid]:
            register(o_champ, o_cid)
            if o_team != team:
                enemies.append(o_champ)
                if pos and o_pos == pos:
                    rival = (o_champ, o_gold)
            else:
                mates[riot_id][0] += 1
                mates[riot_id][1] += win
        games.append({
            "t": t, "d": dur, "w": win, "c": champ, "p": pos,
            "k": k, "de": d, "a": a, "cs": cs, "g": gold,
            "r": rival[0] if rival else None, "rg": rival[1] if rival else None,
            "e": enemies,
        })

    mates_list = sorted(
        ({"id": rid, "g": g, "w": w} for rid, (g, w) in mates.items() if g >= 2),
        key=lambda m: -m["g"])[:7]

    who = conn.execute("SELECT value FROM meta WHERE key='riot_id'").fetchone()
    return {
        "player": who[0] if who else "",
        "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "ver": version,
        "dd": dd,
        "games": games,
        "mates": mates_list,
    }


def generate(conn, puuid, total, path):
    data = build_data(conn, puuid, total)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.replace("__TITLE__", data["player"].split("#")[0] or "Dashboard")
    html = html.replace("__DATA__", payload)
    path.parent.mkdir(exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ · Ranked Solo</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --page:#f9d9dd; --frame:#5c1f2b; --rail:#471620; --panel:#4f1925; --card:#6a2532;
  --card-2:#7a2b39; --coral:#e2474e; --coral-2:#f0695f; --cream:#fdf3c4; --purple:#7d62f5;
  --text:#fbeef0; --muted:#d79aa3; --faint:#a9707a; --good:#7fd6a0; --bad:#ff8a8a;
  --radius-xl:44px; --radius-l:30px; --radius-m:22px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--page);font-family:Poppins,system-ui,sans-serif;color:var(--text);
  min-height:100vh;padding:40px 24px}
img{display:block}
button,input,select{font:inherit;color:inherit}
.app{max-width:1500px;margin:0 auto;background:var(--frame);border-radius:var(--radius-xl);
  padding:26px;display:grid;grid-template-columns:76px minmax(0,1fr) 76px;gap:26px;
  box-shadow:0 40px 80px -30px rgba(92,31,43,.55)}

/* rails */
.rail{background:var(--rail);border-radius:36px;padding:26px 0;display:flex;flex-direction:column;
  align-items:center;gap:26px;position:sticky;top:20px;align-self:start}
.logo{width:40px;height:40px}
.nav{display:flex;flex-direction:column;gap:14px;margin-top:20px}
.nav a{width:46px;height:46px;border-radius:15px;display:grid;place-items:center;color:var(--text);
  opacity:.75;transition:.2s}
.nav a:hover,.nav a.on{opacity:1;color:var(--coral);background:rgba(255,255,255,.04)}
.nav svg{width:22px;height:22px}
.me{width:56px;height:56px;border-radius:50%;background:var(--cream);color:var(--frame);
  display:grid;place-items:center;font-weight:700;font-size:20px;border:3px solid var(--text)}
.mates{display:flex;flex-direction:column;gap:16px;align-items:center}
.mate{position:relative;width:48px;height:48px;border-radius:50%;display:grid;place-items:center;
  font-weight:600;font-size:15px;color:#fff}
.mate .n{position:absolute;right:-6px;bottom:-4px;background:var(--cream);color:var(--frame);
  font-size:10px;font-weight:700;border-radius:10px;padding:1px 6px}
.rail-label{font-size:10px;color:var(--muted);text-align:center;line-height:1.3;padding:0 6px}

/* main grid */
main{display:grid;grid-template-columns:minmax(0,1fr) 400px;gap:28px 30px;
  grid-template-areas:"head head" "hero side" "cards stats" "recent stats" "table table"}
.app>*,main>*{min-width:0}
header{grid-area:head;display:flex;align-items:center;gap:20px;flex-wrap:wrap}
.greet{font-size:28px;font-weight:500;color:var(--muted);flex:1;min-width:260px}
.greet b{color:var(--text);font-weight:700;text-transform:uppercase}
.search{display:flex;align-items:center;gap:10px;background:var(--panel);border-radius:18px;
  padding:12px 18px;width:min(380px,100%)}
.search input{background:none;border:0;outline:0;width:100%}
.search input::placeholder{color:var(--faint)}
.pick{background:var(--panel);border:0;border-radius:18px;padding:12px 16px;outline:0;cursor:pointer}
.pick option{background:var(--frame)}

/* hero */
.hero{grid-area:hero;position:relative;border-radius:var(--radius-l);overflow:hidden;min-height:330px;
  background:var(--coral);display:flex;align-items:center;padding:36px}
.hero .art{position:absolute;inset:0 0 0 30%;background-size:cover;background-position:center 20%}
.hero::after{content:"";position:absolute;inset:0;
  background:linear-gradient(90deg,var(--coral) 0%,var(--coral) 34%,rgba(226,71,78,.75) 52%,rgba(226,71,78,0) 80%)}
.hero .in{position:relative;z-index:1;max-width:460px}
.chips{display:flex;gap:10px;align-items:center;margin-bottom:18px}
.chip{background:var(--cream);color:var(--frame);border-radius:20px;padding:7px 16px;font-weight:600;
  font-size:14px;display:flex;align-items:center;gap:8px}
.chip.dark{background:var(--frame);color:var(--text)}
.hero h1{font-size:52px;line-height:1.05;font-weight:700;margin-bottom:12px}
.hero p{font-size:14px;line-height:1.6;opacity:.95;margin-bottom:22px}
.hero .row{display:flex;align-items:center;gap:14px}
.stack{display:flex}
.stack .av{width:42px;height:42px;border-radius:50%;border:3px solid var(--coral);margin-left:-12px;
  overflow:hidden;background:var(--card)}
.stack .av:first-child{margin-left:0}
.pill{background:#fff;color:var(--frame);border-radius:22px;padding:9px 18px;font-weight:600;font-size:14px}

/* side list */
.side{grid-area:side;display:flex;flex-direction:column;gap:18px}
.item{background:var(--panel);border-radius:var(--radius-m);padding:14px 18px;display:flex;
  align-items:center;gap:18px;cursor:pointer;border:0;text-align:left;width:100%;transition:.2s}
.item:hover,.item.on{background:var(--card)}
.item .ic{width:72px;height:72px;border-radius:18px;overflow:hidden;flex:none;background:var(--card)}
.item .tx{flex:1;min-width:0}
.item .tx b{display:block;font-weight:500;font-size:17px}
.item .tx span{color:var(--coral-2);font-size:14px}
.item .arr{opacity:.8}
.side h3{font-size:15px;font-weight:500;color:var(--muted);padding-left:4px}

/* sections */
section h2{font-size:26px;font-weight:600;margin-bottom:18px;display:flex;align-items:center;
  justify-content:space-between}
section h2 small{font-size:14px;font-weight:400;color:var(--coral-2)}
.cards{grid-area:cards;min-width:0}
.scroller{position:relative}
.track{display:flex;gap:22px;overflow-x:auto;scroll-snap-type:x mandatory;padding:6px 2px 10px;
  scrollbar-width:none}
.track::-webkit-scrollbar{display:none}
.mu{flex:0 0 280px;height:290px;border-radius:var(--radius-l);position:relative;overflow:hidden;
  scroll-snap-align:start;background:var(--card) center/cover;display:flex;flex-direction:column;
  justify-content:space-between;padding:22px}
.mu::before{content:"";position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(60,15,25,.15) 0%,rgba(60,15,25,.35) 45%,rgba(55,12,22,.95) 100%)}
.mu>*{position:relative}
.mu .wr{align-self:flex-start;background:var(--coral);border-radius:16px;padding:6px 14px;font-weight:700;font-size:18px}
.mu .wr.ok{background:var(--purple)}
.mu b{font-size:24px;font-weight:700;display:block}
.mu span{font-size:13px;opacity:.9}
.next{position:absolute;right:-6px;top:50%;transform:translateY(-50%);width:50px;height:50px;
  border-radius:50%;border:0;background:#fff;color:var(--frame);cursor:pointer;display:grid;
  place-items:center;box-shadow:0 8px 20px rgba(0,0,0,.25)}

/* stats */
.stats{grid-area:stats;display:flex;flex-direction:column}
.panel{background:linear-gradient(160deg,var(--panel),#3e1220);border-radius:var(--radius-l);padding:34px 28px;
  flex:1;display:flex;flex-direction:column;align-items:center;gap:30px}
.ring{width:260px;height:260px;border-radius:50%;position:relative;display:grid;place-items:center;
  filter:drop-shadow(0 0 30px rgba(226,71,78,.35))}
.ring::before{content:"";position:absolute;inset:0;border-radius:50%;
  background:conic-gradient(from 210deg,var(--coral) 0,var(--cream) calc(var(--p)*.5),var(--purple) var(--p),rgba(255,255,255,.07) var(--p));
  -webkit-mask:radial-gradient(circle,transparent 58%,#000 59%);mask:radial-gradient(circle,transparent 58%,#000 59%)}
.ring .c{width:190px;height:190px;border-radius:50%;background:#3d111c;display:grid;place-items:center;
  text-align:center;border:1px solid rgba(255,255,255,.08)}
.ring small{display:block;color:var(--muted);font-size:13px}
.ring strong{font-size:44px;font-weight:700;line-height:1.1}
.trio{display:flex;gap:22px;justify-content:center;flex-wrap:wrap}
.dot{display:flex;flex-direction:column;align-items:center;gap:10px}
.dot i{width:78px;height:78px;border-radius:50%;display:grid;place-items:center;font-style:normal;
  font-weight:700;font-size:13px}
.dot b{font-size:20px;font-weight:600}
.roles{width:100%;display:flex;flex-direction:column;gap:12px}
.role{display:grid;grid-template-columns:70px 1fr 74px;gap:12px;align-items:center;font-size:14px}
.bar{height:10px;border-radius:6px;background:rgba(255,255,255,.08);overflow:hidden}
.bar span{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,var(--coral),var(--coral-2))}
.role em{font-style:normal;color:var(--muted);text-align:right}

/* recent */
.recent{grid-area:recent}
.games{display:flex;flex-direction:column;gap:12px}
.game{border-radius:var(--radius-m);padding:12px 18px;display:grid;
  grid-template-columns:56px minmax(0,1.3fr) minmax(0,1fr) auto;gap:16px;align-items:center;
  background:linear-gradient(90deg,var(--card-2) 0%,var(--panel) 60%)}
.game.win{background:linear-gradient(90deg,var(--coral) 0%,#b8394a 30%,var(--panel) 65%)}
.game .ic{width:56px;height:56px;border-radius:16px;overflow:hidden;background:var(--card)}
.game b{font-weight:600;font-size:16px;display:block}
.tag{display:inline-block;background:rgba(0,0,0,.25);border-radius:10px;padding:2px 10px;font-size:12px;margin-top:4px}
.game .kda{font-weight:600}
.game .meta{color:var(--muted);font-size:13px}
.vs{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted)}
.vs .mini{width:32px;height:32px;border-radius:50%;overflow:hidden;background:var(--card)}

/* table */
.table{grid-area:table}
.tools{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:16px}
.tabs{display:flex;background:var(--panel);border-radius:16px;padding:4px}
.tabs button{border:0;background:none;padding:9px 18px;border-radius:12px;cursor:pointer;color:var(--muted)}
.tabs button.on{background:var(--coral);color:#fff}
.min{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:14px;margin-left:auto}
.min input{accent-color:var(--coral)}
.tbl{background:var(--panel);border-radius:var(--radius-l);overflow:auto}
table{width:100%;border-collapse:collapse;min-width:640px}
th{font-weight:500;color:var(--muted);text-align:right;padding:16px 20px;font-size:13px;cursor:pointer;
  user-select:none;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th.s::after{content:" ▾"}
th.s.up::after{content:" ▴"}
td{padding:10px 20px;text-align:right;border-top:1px solid rgba(255,255,255,.05);white-space:nowrap}
tr:hover td{background:rgba(255,255,255,.03)}
.who{display:flex;align-items:center;gap:12px;font-weight:500}
.who .mini{width:38px;height:38px;border-radius:12px;overflow:hidden;background:var(--card)}
.wrcell{display:flex;align-items:center;justify-content:flex-end;gap:10px}
.wrcell .bar{width:90px}
.wrcell .bar span{background:var(--c)}
.good{color:var(--good)} .bad{color:var(--bad)}
.empty{padding:30px;text-align:center;color:var(--muted)}
.ph{width:100%;height:100%;display:grid;place-items:center;font-weight:700;color:var(--frame);background:var(--cream)}
footer{grid-column:1/-1;text-align:center;color:var(--faint);font-size:12px;padding-top:4px}

@media (max-width:1200px){
  main{grid-template-columns:1fr;grid-template-areas:"head" "hero" "side" "stats" "cards" "recent" "table"}
  .side{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr))}
  .side h3{grid-column:1/-1}
}
@media (max-width:820px){
  body{padding:0}
  .app{grid-template-columns:1fr;border-radius:0;padding:16px}
  .rail{flex-direction:row;position:static;padding:12px 16px;border-radius:24px;overflow-x:auto}
  .nav{flex-direction:row;margin:0}
  .rail.right{display:none}
  .hero{padding:24px;min-height:300px}
  .hero h1{font-size:38px}
  .hero .art{inset:0}
  .hero::after{background:linear-gradient(90deg,rgba(226,71,78,.97) 0%,rgba(226,71,78,.85) 55%,rgba(226,71,78,.35) 100%)}
  .greet{font-size:22px}
  .game{grid-template-columns:48px 1fr auto}
  .game .vs{display:none}
  .ring{width:220px;height:220px}.ring .c{width:160px;height:160px}
}
</style>
</head>
<body>
<div class="app">
  <aside class="rail">
    <svg class="logo" viewBox="0 0 40 40" fill="none"><path d="M6 34 L20 6 L34 34" stroke="#fbeef0" stroke-width="5" stroke-linejoin="round"/><path d="M13 24h14" stroke="#e2474e" stroke-width="5"/></svg>
    <nav class="nav">
      <a href="#inicio" class="on" title="Inicio"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3 3 10v10a1 1 0 0 0 1 1h5v-6h6v6h5a1 1 0 0 0 1-1V10z"/></svg></a>
      <a href="#dificiles" title="Matchups difíciles"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M14.5 17.5 3 6V3h3l11.5 11.5M13 19l6-6M16 16l4 4M19 21l2-2"/></svg></a>
      <a href="#estadistica" title="Estadística"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M11 3a9 9 0 1 0 9.95 10H11z"/><path d="M13 2v9h9a9 9 0 0 0-9-9z" opacity=".6"/></svg></a>
      <a href="#recientes" title="Últimas partidas"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg></a>
      <a href="#tabla" title="Todos los matchups"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h10"/></svg></a>
    </nav>
  </aside>

  <main id="inicio">
    <header>
      <div class="greet" id="greet"></div>
      <select class="pick" id="champSel" aria-label="Filtrar por campeón"></select>
      <label class="search">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" opacity=".7"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input id="q" placeholder="Buscar rival..." autocomplete="off">
      </label>
    </header>

    <div class="hero" id="hero"></div>
    <div class="side" id="side"></div>

    <section class="cards" id="dificiles">
      <h2>Matchups más difíciles <small id="diffNote"></small></h2>
      <div class="scroller">
        <div class="track" id="track"></div>
        <button class="next" id="next" aria-label="Siguiente"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="m9 6 6 6-6 6"/></svg></button>
      </div>
    </section>

    <section class="stats" id="estadistica">
      <h2>Tu estadística</h2>
      <div class="panel" id="panel"></div>
    </section>

    <section class="recent" id="recientes">
      <h2>Últimas partidas <small id="recentNote"></small></h2>
      <div class="games" id="games"></div>
    </section>

    <section class="table" id="tabla">
      <h2>Todos los matchups</h2>
      <div class="tools">
        <div class="tabs" id="tabs">
          <button data-m="lane" class="on">Rival de línea</button>
          <button data-m="team">Equipo enemigo</button>
        </div>
        <label class="min">Mínimo de partidas <input type="range" id="min" min="1" max="15" value="3"> <b id="minV">3</b></label>
      </div>
      <div class="tbl" id="tbl"></div>
    </section>
  </main>

  <aside class="rail right">
    <div class="me" id="me"></div>
    <div class="rail-label">Con quién<br>más juegas</div>
    <div class="mates" id="mates"></div>
  </aside>
  <footer id="foot"></footer>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const ROLE = {TOP:'Top',JUNGLE:'Jungla',MIDDLE:'Mid',BOTTOM:'ADC',UTILITY:'Support','':'—'};
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = (w, g) => g ? Math.round(100 * w / g) : 0;
const kda = s => ((s.k + s.a) / Math.max(1, s.de)).toFixed(2);
const fmtDate = t => new Date(t).toLocaleDateString('es-MX', {day:'2-digit', month:'short'});
const ddId = n => D.dd[n];
const icon = n => ddId(n) && D.ver ? `https://ddragon.leagueoflegends.com/cdn/${D.ver}/img/champion/${ddId(n)}.png` : null;
const splash = n => ddId(n) ? `https://ddragon.leagueoflegends.com/cdn/img/champion/splash/${ddId(n)}_0.jpg` : null;
const centered = n => ddId(n) ? `https://ddragon.leagueoflegends.com/cdn/img/champion/centered/${ddId(n)}_0.jpg` : null;
const img = (n, cls = '') => {
  const u = icon(n);
  return u ? `<img src="${u}" alt="${esc(n)}" loading="lazy" width="100%" height="100%" class="${cls}">`
           : `<div class="ph">${esc((n || '?').slice(0, 2))}</div>`;
};

const state = {champ: '', mode: 'lane', min: 3, q: '', sort: 'g', dir: -1};

function agg(games, keyFn) {
  const m = new Map();
  for (const g of games) {
    for (const key of [].concat(keyFn(g))) {
      if (key == null) continue;
      const s = m.get(key) || {name: key, g: 0, w: 0, k: 0, de: 0, a: 0, cs: 0, d: 0, gd: 0, gdn: 0};
      s.g++; s.w += g.w; s.k += g.k; s.de += g.de; s.a += g.a; s.cs += g.cs; s.d += g.d;
      if (g.rg != null && key === g.r) { s.gd += g.g - g.rg; s.gdn++; }
      m.set(key, s);
    }
  }
  return [...m.values()];
}

const filtered = () => state.champ ? D.games.filter(g => g.c === state.champ) : D.games;
const myChamps = agg(D.games, g => g.c).sort((a, b) => b.g - a.g);

function renderHeader() {
  const h = new Date().getHours();
  const hi = h < 12 ? 'Buenos días' : h < 19 ? 'Buenas tardes' : 'Buenas noches';
  const name = D.player.split('#')[0];
  $('greet').innerHTML = `${hi}, <b>${esc(name)}</b>`;
  $('me').textContent = name.slice(0, 1).toUpperCase();
  $('champSel').innerHTML = `<option value="">Todos tus campeones</option>` +
    myChamps.map(c => `<option value="${esc(c.name)}">${esc(c.name)} (${c.g})</option>`).join('');
  $('foot').textContent = `${D.player} · Ranked Solo/Duo · generado ${D.generated} · datos de la API de Riot Games`;
}

function renderHero(G) {
  const name = state.champ || myChamps[0]?.name;
  const s = agg(G.filter(g => g.c === name), g => g.c)[0];
  if (!s) { $('hero').innerHTML = '<div class="in"><h1>Sin partidas</h1></div>'; return; }
  const mins = s.d / 60;
  const top3 = myChamps.slice(0, 3);
  const bg = splash(name);
  $('hero').innerHTML = `
    ${bg ? `<div class="art" style="background-image:url('${bg}')"></div>` : ''}
    <div class="in">
      <div class="chips">
        <span class="chip">${state.champ ? 'Filtrando' : '★ Más jugado'}</span>
        <span class="chip dark">${s.g} partidas</span>
      </div>
      <h1>${esc(name)}</h1>
      <p>Winrate de <b>${pct(s.w, s.g)}%</b> (${s.w}V - ${s.g - s.w}D) con KDA de <b>${kda(s)}</b>,
         ${(s.k / s.g).toFixed(1)} / ${(s.de / s.g).toFixed(1)} / ${(s.a / s.g).toFixed(1)} en promedio
         y <b>${(s.cs / mins).toFixed(1)}</b> CS por minuto.</p>
      <div class="row">
        <div class="stack">${top3.map(c => `<div class="av" title="${esc(c.name)}">${img(c.name)}</div>`).join('')}</div>
        <span class="pill">${myChamps.length} campeones jugados</span>
      </div>
    </div>`;
}

function renderSide() {
  $('side').innerHTML = `<h3>Tus campeones más jugados</h3>` + myChamps.slice(0, 3).map(c => `
    <button class="item ${state.champ === c.name ? 'on' : ''}" data-c="${esc(c.name)}">
      <div class="ic">${img(c.name)}</div>
      <div class="tx"><b>${esc(c.name)}</b><span>${c.g} partidas · ${pct(c.w, c.g)}% winrate</span></div>
      <svg class="arr" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m9 6 6 6-6 6"/></svg>
    </button>`).join('');
  $('side').querySelectorAll('.item').forEach(b => b.onclick = () => {
    setChamp(state.champ === b.dataset.c ? '' : b.dataset.c);
  });
}

function renderCards(G) {
  const minG = Math.max(state.min, 3);
  const rows = agg(G, g => g.r).filter(s => s.g >= minG)
    .sort((a, b) => a.w / a.g - b.w / b.g || b.g - a.g).slice(0, 10);
  $('diffNote').textContent = `rival de línea · ${minG}+ partidas`;
  $('track').innerHTML = rows.length ? rows.map(s => {
    const wr = pct(s.w, s.g), u = centered(s.name);
    return `<div class="mu" style="${u ? `background-image:url('${u}')` : ''}">
      <span class="wr ${wr >= 50 ? 'ok' : ''}">${wr}%</span>
      <div><b>${esc(s.name)}</b><span>${s.w}V - ${s.g - s.w}D · tu KDA ${kda(s)}</span></div>
    </div>`;
  }).join('') : `<div class="empty">Aún no hay rivales con ${minG} o más partidas.</div>`;
}

function renderStats(G) {
  const g = G.length, w = G.reduce((t, x) => t + x.w, 0);
  const tot = G.reduce((t, x) => ({k: t.k + x.k, de: t.de + x.de, a: t.a + x.a, cs: t.cs + x.cs, d: t.d + x.d}),
                       {k: 0, de: 0, a: 0, cs: 0, d: 0});
  const hours = tot.d / 3600;
  const roles = agg(G, x => x.p).sort((a, b) => b.g - a.g);
  const wr = pct(w, g);
  $('panel').innerHTML = `
    <div class="ring" style="--p:${wr}%"><div class="c"><div>
      <small>Winrate</small><strong>${wr}%</strong><small>${g} partidas · ${hours.toFixed(0)}h</small>
    </div></div></div>
    <div class="trio">
      <div class="dot"><i style="background:var(--coral)">Victorias</i><b>${w}-${g - w}</b></div>
      <div class="dot"><i style="background:var(--cream);color:var(--frame)">KDA</i><b>${g ? kda(tot) : '—'}</b></div>
      <div class="dot"><i style="background:var(--purple)">CS/min</i><b>${tot.d ? (tot.cs / (tot.d / 60)).toFixed(1) : '—'}</b></div>
    </div>
    <div class="roles">${roles.map(r => `
      <div class="role"><span>${ROLE[r.name] ?? r.name}</span>
        <div class="bar"><span style="width:${100 * r.g / g}%"></span></div>
        <em>${r.g} · ${pct(r.w, r.g)}%</em></div>`).join('')}
    </div>`;
}

function renderRecent(G) {
  const last = G.slice(0, 6);
  $('recentNote').textContent = G.length ? `${fmtDate(G[G.length - 1].t)} a ${fmtDate(G[0].t)}` : '';
  $('games').innerHTML = last.map(x => `
    <div class="game ${x.w ? 'win' : ''}">
      <div class="ic">${img(x.c)}</div>
      <div><b>${esc(x.c)}</b><span class="tag">${x.w ? 'Victoria' : 'Derrota'} · ${ROLE[x.p] ?? x.p}</span></div>
      <div><div class="kda">${x.k} / ${x.de} / ${x.a}</div>
        <div class="meta">${x.cs} CS · ${Math.floor(x.d / 60)}:${String(x.d % 60).padStart(2, '0')} · ${fmtDate(x.t)}</div></div>
      <div class="vs">${x.r ? `vs <div class="mini">${img(x.r)}</div>` : ''}</div>
    </div>`).join('') || '<div class="empty">Sin partidas.</div>';
}

function renderTable(G) {
  const lane = state.mode === 'lane';
  let rows = agg(G, lane ? (g => g.r) : (g => g.e)).filter(s => s.g >= state.min);
  const q = state.q.trim().toLowerCase();
  if (q) rows = rows.filter(s => s.name.toLowerCase().includes(q));
  const val = {name: s => s.name, g: s => s.g, wr: s => s.w / s.g, kda: s => (s.k + s.a) / Math.max(1, s.de),
               gd: s => s.gdn ? s.gd / s.gdn : 0};
  rows.sort((a, b) => {
    const A = val[state.sort](a), B = val[state.sort](b);
    return (A > B ? 1 : A < B ? -1 : b.g - a.g) * state.dir;
  });
  const cols = [['name', 'Rival'], ['g', 'Partidas'], ['wr', 'Winrate'], ['kda', 'Tu KDA']];
  if (lane) cols.push(['gd', 'Dif. oro']);
  const head = cols.map(([k, t]) =>
    `<th data-k="${k}" class="${state.sort === k ? 's' + (state.dir > 0 ? ' up' : '') : ''}">${t}</th>`).join('');
  const body = rows.map(s => {
    const wr = pct(s.w, s.g);
    const color = wr >= 55 ? 'var(--good)' : wr <= 45 ? 'var(--bad)' : 'var(--cream)';
    const gd = s.gdn ? Math.round(s.gd / s.gdn) : null;
    return `<tr>
      <td><div class="who"><div class="mini">${img(s.name)}</div>${esc(s.name)}</div></td>
      <td>${s.g} <span style="color:var(--muted)">(${s.w}-${s.g - s.w})</span></td>
      <td><div class="wrcell" style="--c:${color}"><div class="bar"><span style="width:${wr}%"></span></div><b>${wr}%</b></div></td>
      <td>${kda(s)}</td>
      ${lane ? `<td class="${gd > 0 ? 'good' : gd < 0 ? 'bad' : ''}">${gd == null ? '—' : (gd > 0 ? '+' : '') + gd.toLocaleString('es-MX')}</td>` : ''}
    </tr>`;
  }).join('');
  $('tbl').innerHTML = rows.length
    ? `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`
    : `<div class="empty">Ningún rival coincide con el filtro.</div>`;
  $('tbl').querySelectorAll('th').forEach(th => th.onclick = () => {
    const k = th.dataset.k;
    if (state.sort === k) state.dir *= -1; else { state.sort = k; state.dir = k === 'name' ? 1 : -1; }
    renderTable(filtered());
  });
}

function renderMates() {
  const colors = ['var(--coral)', 'var(--purple)', '#c9853a', '#3d9b8f', '#b84f9e', '#5a7fd6', '#8e6b4a'];
  $('mates').innerHTML = D.mates.length ? D.mates.map((m, i) => {
    const n = m.id.split('#')[0];
    return `<div class="mate" style="background:${colors[i % colors.length]}" title="${esc(m.id)}: ${m.g} partidas juntos, ${pct(m.w, m.g)}% winrate">
      ${esc(n.slice(0, 2).toUpperCase())}<span class="n">${m.g}</span></div>`;
  }).join('') : '<div class="rail-label">Nadie repetido</div>';
}

function renderAll() {
  const G = filtered();
  renderHero(G); renderSide(); renderCards(G); renderStats(G); renderRecent(G); renderTable(G);
  $('champSel').value = state.champ;
}
function setChamp(c) { state.champ = c; renderAll(); }

renderHeader(); renderMates(); renderAll();
$('champSel').onchange = e => setChamp(e.target.value);
$('q').oninput = e => { state.q = e.target.value; renderTable(filtered());
  if (state.q) $('tabla').scrollIntoView({behavior: 'smooth', block: 'start'}); };
$('min').oninput = e => { state.min = +e.target.value; $('minV').textContent = state.min; renderCards(filtered()); renderTable(filtered()); };
$('tabs').onclick = e => {
  const b = e.target.closest('button'); if (!b) return;
  state.mode = b.dataset.m;
  $('tabs').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  if (state.mode === 'team' && state.sort === 'gd') state.sort = 'g';
  renderTable(filtered());
};
$('next').onclick = () => $('track').scrollBy({left: 300, behavior: 'smooth'});
document.querySelectorAll('.nav a').forEach(a => a.onclick = () => {
  document.querySelectorAll('.nav a').forEach(x => x.classList.toggle('on', x === a));
});
</script>
</body>
</html>
"""