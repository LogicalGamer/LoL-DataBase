"""
Genera el resumen completo de una partida (la última de Ranked Solo) en HTML.
Lo usa lol_db.py con --last-match; guarda este archivo en la misma carpeta.
"""
import json
from datetime import datetime

import requests

DD = "https://ddragon.leagueoflegends.com"
SHARDS = {5001: "Vida escalable", 5002: "Armadura", 5003: "Resistencia mágica", 5005: "Velocidad de ataque",
          5007: "Aceleración de habilidad", 5008: "Fuerza adaptable", 5010: "Velocidad de movimiento",
          5011: "Vida", 5013: "Tenacidad y resistencia a ralentización"}
MONSTERS = {"DRAGON": "Dragón", "BARON_NASHOR": "Barón Nashor", "RIFTHERALD": "Heraldo",
            "HORDE": "Larva del Vacío", "ATAKHAN": "Atakhan"}
DRAGONS = {"FIRE_DRAGON": "Dragón Infernal", "WATER_DRAGON": "Dragón del Océano",
           "EARTH_DRAGON": "Dragón de la Montaña", "AIR_DRAGON": "Dragón de las Nubes",
           "HEXTECH_DRAGON": "Dragón Hextech", "CHEMTECH_DRAGON": "Dragón Quimtech",
           "ELDER_DRAGON": "Dragón Ancestral"}
LANES = {"TOP_LANE": "superior", "MID_LANE": "central", "BOT_LANE": "inferior"}
TOWERS = {"OUTER_TURRET": "exterior", "INNER_TURRET": "interior", "BASE_TURRET": "de inhibidor"}
MULTI = {2: "Doble kill", 3: "Triple kill", 4: "Quadra kill", 5: "¡PENTAKILL!"}


def ddragon():
    """Versión, campeones, objetos, hechizos y runas (es_MX) desde Data Dragon."""
    out = {"ver": None, "champs": {}, "items": {}, "spells": {}, "runes": {}}
    try:
        ver = requests.get(f"{DD}/api/versions.json", timeout=15).json()[0]
        get = lambda f: requests.get(f"{DD}/cdn/{ver}/data/es_MX/{f}", timeout=15).json()
        out["champs"] = {int(c["key"]): (c["id"], c["name"]) for c in get("champion.json")["data"].values()}
        out["items"] = {int(k): v["name"] for k, v in get("item.json")["data"].items()}
        out["spells"] = {int(s["key"]): (s["id"], s["name"]) for s in get("summoner.json")["data"].values()}
        for style in get("runesReforged.json"):
            out["runes"][style["id"]] = (style["name"], style["icon"])
            for slot in style["slots"]:
                for r in slot["runes"]:
                    out["runes"][r["id"]] = (r["name"], r["icon"])
        out["ver"] = ver
    except Exception:
        print("  Aviso: no se pudieron cargar los datos de Data Dragon; el resumen saldrá sin imágenes.")
    return out


def building(e):
    lane = LANES.get(e.get("laneType"), "")
    if e.get("buildingType") == "INHIBITOR_BUILDING":
        return f"Inhibidor {lane}".strip()
    if e.get("towerType") == "NEXUS_TURRET":
        return "Torre del Nexo"
    return f"Torre {TOWERS.get(e.get('towerType'), '')} {lane}".replace("  ", " ").strip()


def timeline_data(tl, me, rival, team_of):
    """Oro por minuto, compras, orden de habilidades y eventos, desde el timeline de Riot."""
    frames = tl["info"]["frames"]
    my_team = team_of[me]
    gold = []
    for f in frames:
        pf = f["participantFrames"]
        team = sum(v["totalGold"] * (1 if team_of[int(k)] == my_team else -1) for k, v in pf.items())
        lane = pf[str(me)]["totalGold"] - pf[str(rival)]["totalGold"] if rival else None
        gold.append([round(f["timestamp"] / 60000, 2), team, lane])

    def snap(minute):
        if len(frames) <= minute:
            return None
        pf = frames[minute]["participantFrames"]
        cs = lambda x: x["minionsKilled"] + x["jungleMinionsKilled"]
        a = pf[str(me)]
        b = pf[str(rival)] if rival else None
        return {"gold": (a["totalGold"], b and b["totalGold"]), "cs": (cs(a), b and cs(b)),
                "xp": (a["xp"], b and b["xp"])}

    purchases, skills, events = [], [], []
    for f in frames:
        for e in f["events"]:
            t, kind, pid = e["timestamp"], e["type"], e.get("participantId")
            if kind == "ITEM_PURCHASED" and pid == me:
                purchases.append([t, e["itemId"]])
            elif kind == "ITEM_UNDO" and pid == me and e.get("beforeId"):
                for j in range(len(purchases) - 1, -1, -1):
                    if purchases[j][1] == e["beforeId"]:
                        del purchases[j]
                        break
            elif kind == "SKILL_LEVEL_UP" and pid == me and e.get("levelUpType") == "NORMAL":
                skills.append(e["skillSlot"])
            elif kind == "CHAMPION_KILL":
                killer, victim = e.get("killerId", 0), e["victimId"]
                if me in (killer, victim) or me in e.get("assistingParticipantIds", []):
                    events.append({"t": t, "k": "kill" if killer == me else "death" if victim == me else "assist",
                                   "a": killer, "b": victim})
            elif kind == "ELITE_MONSTER_KILL":
                name = DRAGONS.get(e.get("monsterSubType")) or MONSTERS.get(e["monsterType"], e["monsterType"])
                ally = e.get("killerTeamId") == my_team
                prev = events[-1] if events else None
                # Las larvas salen en grupo: se juntan en un solo evento.
                if prev and prev["k"] == "obj" and prev["x"] == name and prev["ally"] == ally and t - prev["t"] < 90000:
                    prev["n"] += 1
                else:
                    events.append({"t": t, "k": "obj", "x": name, "ally": ally, "n": 1})
            elif kind == "BUILDING_KILL":
                # teamId es el dueño de la estructura destruida.
                events.append({"t": t, "k": "bld", "x": building(e), "ally": e.get("teamId") != my_team})

    # Agrupa las compras por visita a la tienda (menos de 45 s entre una y otra).
    trips = []
    for t, item in purchases:
        if trips and t - trips[-1]["last"] < 45000:
            trips[-1]["items"].append(item)
            trips[-1]["last"] = t
        else:
            trips.append({"t": t, "last": t, "items": [item]})

    return {"gold": gold, "trips": [[tr["t"], tr["items"]] for tr in trips], "skills": skills,
            "events": events, "at": {m: snap(m) for m in (10, 15)}}


def build(match, timeline, puuid):
    dd = ddragon()
    info = match["info"]
    parts = info["participants"]
    me = next(p for p in parts if p["puuid"] == puuid)
    mins = max(1, info["gameDuration"]) / 60
    team_kills = {t: sum(p["kills"] for p in parts if p["teamId"] == t) for t in (100, 200)}
    team_dmg = {t: sum(p["totalDamageDealtToChampions"] for p in parts if p["teamId"] == t) for t in (100, 200)}

    champ = lambda cid, fallback: dd["champs"].get(cid, (fallback, fallback))
    rune = lambda rid: {"n": dd["runes"].get(rid, ("", ""))[0], "i": dd["runes"].get(rid, ("", ""))[1]}

    def spell(sid):
        key, name = dd["spells"].get(sid, ("", ""))
        return {"n": name, "i": key}

    players = []
    for p in parts:
        cid, name = champ(p["championId"], p["championName"])
        styles = p["perks"]["styles"]
        players.append({
            "id": p["participantId"], "team": p["teamId"], "me": p["puuid"] == puuid, "win": p["win"],
            "name": p.get("riotIdGameName") or p.get("summonerName", ""), "tag": p.get("riotIdTagline", ""),
            "c": name, "cid": cid, "pos": p.get("teamPosition") or "", "lvl": p["champLevel"],
            "k": p["kills"], "d": p["deaths"], "a": p["assists"],
            "cs": p["totalMinionsKilled"] + p["neutralMinionsKilled"], "gold": p["goldEarned"],
            "dmg": p["totalDamageDealtToChampions"], "vis": p["visionScore"],
            "items": [p[f"item{i}"] for i in range(7)],
            "spells": [spell(p["summoner1Id"]), spell(p["summoner2Id"])],
            "ks": rune(styles[0]["selections"][0]["perk"]), "sub": rune(styles[1]["style"]),
            "kp": round(100 * (p["kills"] + p["assists"]) / max(1, team_kills[p["teamId"]])),
        })
    my = next(p for p in players if p["me"])
    rival = next((p for p in players if my["pos"] and p["team"] != my["team"] and p["pos"] == my["pos"]), None)

    teams = {}
    for t in info["teams"]:
        teams[t["teamId"]] = {
            "win": t["win"],
            "bans": [{"cid": champ(b["championId"], "")[0], "c": champ(b["championId"], "")[1]}
                     for b in t["bans"] if b["championId"] > 0],
            "obj": {k: v["kills"] for k, v in t["objectives"].items()},
        }

    tl = None
    if timeline:
        tl = timeline_data(timeline, my["id"], rival and rival["id"], {p["id"]: p["team"] for p in players})

    ch = me.get("challenges", {})
    badges = []
    if me["largestMultiKill"] >= 2:
        badges.append(MULTI[min(5, me["largestMultiKill"])])
    if me["firstBloodKill"]:
        badges.append("Primera sangre")
    elif me["firstBloodAssist"]:
        badges.append("Asistencia en primera sangre")
    if me["firstTowerKill"]:
        badges.append("Primera torre")
    if ch.get("soloKills"):
        badges.append(f"{ch['soloKills']} solo kill" + ("s" if ch["soloKills"] > 1 else ""))
    if me["largestKillingSpree"] >= 5:
        badges.append(f"Racha de {me['largestKillingSpree']}")
    if me["objectivesStolen"]:
        badges.append("Robaste un objetivo")

    k, d, a = my["k"], my["d"], my["a"]
    dead = me["totalTimeSpentDead"]
    tiles = [
        ["KDA", f"{(k + a) / max(1, d):.2f}", f"{k} / {d} / {a}"],
        ["Participación", f"{my['kp']}%", "en asesinatos del equipo"],
        ["CS", f"{my['cs']}", f"{my['cs'] / mins:.1f} por minuto"],
        ["Oro", f"{my['gold']:,}", f"{my['gold'] / mins:.0f} por minuto"],
        ["Daño a campeones", f"{my['dmg']:,}",
         f"{100 * my['dmg'] / max(1, team_dmg[my['team']]):.0f}% de tu equipo"],
        ["Daño recibido", f"{me['totalDamageTaken']:,}", f"{me['damageSelfMitigated']:,} mitigado"],
        ["Visión", f"{my['vis']}", f"{my['vis'] / mins:.2f}/min · {me['visionWardsBoughtInGame']} de control"],
        ["Tiempo muerto", f"{dead // 60}:{dead % 60:02d}", f"{100 * dead / (mins * 60):.0f}% de la partida"],
    ]

    lane = []
    if rival:
        for m in (10, 15):
            s = tl and tl["at"][m]
            if s:
                lane += [{"l": f"Oro al min {m}", "a": s["gold"][0], "b": s["gold"][1]},
                         {"l": f"CS al min {m}", "a": s["cs"][0], "b": s["cs"][1]}]
        lane += [{"l": "Asesinatos", "a": k, "b": rival["k"]},
                 {"l": "Oro final", "a": my["gold"], "b": rival["gold"]},
                 {"l": "CS final", "a": my["cs"], "b": rival["cs"]},
                 {"l": "Daño a campeones", "a": my["dmg"], "b": rival["dmg"]},
                 {"l": "Visión", "a": my["vis"], "b": rival["vis"]}]

    item_ids = {i for p in players for i in p["items"] if i}
    if tl:
        item_ids |= {i for _, items in tl["trips"] for i in items}
    styles = me["perks"]["styles"]
    who = f"{me.get('riotIdGameName', '')}#{me.get('riotIdTagline', '')}"
    return {
        "player": who,
        "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "ver": dd["ver"],
        "match": {"id": match["metadata"]["matchId"], "t": info["gameCreation"], "d": info["gameDuration"],
                  "patch": ".".join(str(info.get("gameVersion", "")).split(".")[:2]),
                  "win": me["win"], "remake": bool(info["gameDuration"] < 300 or me.get("gameEndedInEarlySurrender"))},
        "players": players,
        "rival": rival and rival["id"],
        "teams": teams,
        "tiles": tiles,
        "badges": badges,
        "lane": lane,
        "runes": {"styles": [{"style": rune(s["style"]), "perks": [rune(x["perk"]) for x in s["selections"]]}
                             for s in styles],
                  "shards": [SHARDS.get(me["perks"]["statPerks"].get(k), "?") for k in ("offense", "flex", "defense")]},
        "items": {i: dd["items"].get(i, str(i)) for i in item_ids},
        "tl": tl,
    }


def generate(data, path):
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    me = next(p for p in data["players"] if p["me"])
    html = TEMPLATE.replace("__TITLE__", f"{me['c']} · {data['player'].split('#')[0]}")
    html = html.replace("__DATA__", payload)
    path.parent.mkdir(exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ · Última partida</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --page:#f9d9dd; --frame:#5c1f2b; --panel:#4f1925; --card:#6a2532; --card-2:#7a2b39;
  --coral:#e2474e; --coral-2:#f0695f; --cream:#fdf3c4; --purple:#7d62f5;
  --text:#fbeef0; --muted:#d79aa3; --faint:#a9707a; --good:#7fd6a0; --bad:#ff8a8a;
  --ally:#e2474e; --enemy:#7d62f5; --grid:rgba(251,238,240,.09);
  --radius-xl:44px; --radius-l:30px; --radius-m:22px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--page);font-family:Poppins,system-ui,sans-serif;color:var(--text);
  min-height:100vh;padding:40px 24px}
img{display:block}
button{font:inherit;color:inherit;border:0;background:none;cursor:pointer}
.app{max-width:1320px;margin:0 auto;background:var(--frame);border-radius:var(--radius-xl);padding:30px;
  display:grid;grid-template-columns:minmax(0,1fr) 400px;gap:28px 30px;
  grid-template-areas:"top top" "hero lane" "tiles tiles" "chart obj" "board board" "build events" "foot foot";
  box-shadow:0 40px 80px -30px rgba(92,31,43,.55)}
.app>*{min-width:0}
h2{font-size:24px;font-weight:600;margin-bottom:16px;display:flex;align-items:baseline;justify-content:space-between;gap:12px}
h2 small{font-size:13px;font-weight:400;color:var(--muted)}
h3{font-size:15px;font-weight:500;color:var(--muted);margin:22px 0 12px}
.panel{background:var(--panel);border-radius:var(--radius-l);padding:24px}
.empty{color:var(--faint);font-size:14px}
.ph{background:var(--card)}

header{grid-area:top;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
header .greet{font-size:26px;font-weight:500;color:var(--muted);flex:1}
header .greet b{color:var(--text);font-weight:700;text-transform:uppercase}
header .id{font-size:13px;color:var(--faint)}

/* hero */
.hero{grid-area:hero;position:relative;border-radius:var(--radius-l);overflow:hidden;min-height:330px;
  background:var(--card);display:flex;align-items:center;padding:36px}
.hero .art{position:absolute;inset:0 0 0 28%;background-size:cover;background-position:center 20%}
.hero::after{content:"";position:absolute;inset:0;
  background:linear-gradient(90deg,var(--hero) 0%,var(--hero) 34%,color-mix(in srgb,var(--hero) 70%,transparent) 55%,transparent 85%)}
.hero.win{--hero:#a93a45}.hero.loss{--hero:#3d1420}.hero.remake{--hero:#4f1925}
.hero .in{position:relative;z-index:1;max-width:480px}
.chips{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}
.chip{background:var(--cream);color:var(--frame);border-radius:20px;padding:6px 15px;font-weight:600;font-size:13px}
.chip.dark{background:rgba(0,0,0,.28);color:var(--text)}
.res{border-radius:20px;padding:6px 15px;font-weight:700;font-size:13px;text-transform:uppercase;letter-spacing:.06em;
  display:flex;align-items:center;gap:7px;background:rgba(0,0,0,.28)}
.res::before{content:"";width:9px;height:9px;border-radius:50%;background:currentColor}
.res.good{color:var(--good)}.res.bad{color:var(--bad)}.res.neutral{color:var(--muted)}
.hero h1{font-size:54px;line-height:1.02;font-weight:700;margin-bottom:8px}
.hero .kda{font-size:26px;font-weight:600;margin-bottom:6px}
.hero .kda .d{color:var(--bad)}
.hero .kda .r{font-size:15px;font-weight:500;color:var(--muted);margin-left:8px}
.hero p{font-size:14px;opacity:.9;margin-bottom:18px}
.badges{display:flex;flex-wrap:wrap;gap:8px}
.badge{background:rgba(253,243,196,.14);border:1px solid rgba(253,243,196,.35);color:var(--cream);
  border-radius:14px;padding:4px 12px;font-size:12px;font-weight:600}

/* comparación tú vs rival / objetivos */
.lane{grid-area:lane}
.obj{grid-area:obj}
.vs-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:10px}
.vs-head .who{display:flex;align-items:center;gap:10px;font-weight:600;font-size:14px;min-width:0}
.vs-head .who.r{flex-direction:row-reverse;text-align:right}
.vs-head .who img,.vs-head .who .ph{width:40px;height:40px;border-radius:12px;flex:none}
.vs-head .who span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cmp{display:grid;grid-template-columns:62px minmax(0,1fr) 62px;align-items:center;gap:4px 10px;margin-bottom:12px}
.cmp .l{grid-column:1/-1;text-align:center;font-size:12px;color:var(--muted)}
.cmp .v{font-size:14px;font-weight:600;font-variant-numeric:tabular-nums}
.cmp .v.b{text-align:right}
.cmp .v.lead::after{content:" ▲";font-size:9px;color:var(--cream)}
.cmp .v.b.lead::after{content:""}.cmp .v.b.lead::before{content:"▲ ";font-size:9px;color:var(--cream)}
.split{display:flex;height:8px;gap:2px}
.split i{display:block;height:100%;border-radius:4px;min-width:4px}
.split .a{background:var(--ally)}.split .b{background:var(--enemy)}
.key{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:4px}
.key span{display:flex;align-items:center;gap:6px}
.key i{width:10px;height:10px;border-radius:3px;display:block}

/* tiles */
.tiles{grid-area:tiles;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px}
.tile{background:var(--panel);border-radius:var(--radius-m);padding:18px 20px}
.tile .l{font-size:13px;color:var(--muted)}
.tile .v{font-size:28px;font-weight:700;margin:2px 0;font-variant-numeric:tabular-nums}
.tile .s{font-size:12px;color:var(--coral-2)}

/* gráfica */
.chart{grid-area:chart}
.tabs{display:flex;gap:6px;background:var(--frame);border-radius:14px;padding:4px}
.tab{padding:6px 14px;border-radius:10px;font-size:13px;color:var(--muted)}
.tab.on{background:var(--card-2);color:var(--text)}
#chart{position:relative;margin-top:6px}
#chart svg{display:block;overflow:visible}
#chart text{fill:var(--muted);font-size:11px;font-family:Poppins,system-ui,sans-serif}
.tip{position:absolute;pointer-events:none;background:var(--frame);border:1px solid var(--card-2);border-radius:12px;
  padding:8px 12px;font-size:12px;white-space:nowrap;display:none;box-shadow:0 10px 24px rgba(0,0,0,.35);z-index:2}
.tip b{display:block;font-size:15px}

/* marcador */
.board{grid-area:board;display:grid;gap:22px}
.team-h{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.team-h .t{font-size:18px;font-weight:600;display:flex;align-items:center;gap:8px}
.team-h .t::before{content:"";width:12px;height:12px;border-radius:4px;background:var(--side)}
.team-h .tot{font-size:13px;color:var(--muted);flex:1}
.bans{display:flex;gap:5px;align-items:center;font-size:12px;color:var(--faint)}
.bans img,.bans .ph{width:24px;height:24px;border-radius:7px;filter:grayscale(1);opacity:.7}
.rows{display:grid;gap:6px}
.prow{display:grid;grid-template-columns:52px 24px 24px minmax(110px,1.3fr) 104px 74px 64px minmax(110px,1fr) 222px;
  align-items:center;gap:10px;padding:8px 12px;border-radius:16px;background:var(--panel)}
.prow.me{background:var(--card);box-shadow:inset 0 0 0 2px var(--cream)}
.prow.hd{background:none;padding-top:0;padding-bottom:0;font-size:11px;color:var(--faint)}
.ch{position:relative;width:46px;height:46px}
.ch img,.ch .ph{width:46px;height:46px;border-radius:14px}
.ch .lv{position:absolute;right:-5px;bottom:-4px;background:var(--frame);border-radius:8px;font-size:10px;font-weight:700;padding:0 5px}
.stk{display:grid;gap:3px}
.stk img,.stk .ph{width:22px;height:22px;border-radius:6px}
.stk .rn{border-radius:50%;background:rgba(0,0,0,.35)}
.nm{min-width:0}
.nm b{display:block;font-weight:500;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nm span{font-size:12px;color:var(--faint)}
.num{font-size:14px;font-weight:600;font-variant-numeric:tabular-nums}
.num small{display:block;font-size:11px;font-weight:400;color:var(--muted)}
.dmg{font-size:12px;font-variant-numeric:tabular-nums}
.dmg .bar{height:8px;border-radius:4px;background:rgba(255,255,255,.07);margin-top:4px}
.dmg .bar i{display:block;height:100%;border-radius:4px;background:var(--side)}
.items{display:flex;gap:3px}
.items img,.items .ph{width:28px;height:28px;border-radius:7px}
.items .ph{opacity:.45}
.items .tr{margin-left:4px;border-radius:50%}

/* build */
.build{grid-area:build}
.trips{display:flex;flex-wrap:wrap;gap:10px 6px;align-items:flex-start}
.trip{background:var(--frame);border-radius:14px;padding:8px 10px}
.trip .its{display:flex;gap:3px}
.trip img,.trip .ph{width:32px;height:32px;border-radius:8px}
.trip span{display:block;font-size:11px;color:var(--muted);text-align:center;margin-top:4px}
.arrow{align-self:center;color:var(--faint);font-size:13px}
.skills{overflow-x:auto;padding-bottom:4px}
.sk{display:grid;gap:3px;width:max-content}
.sk .r{display:flex;gap:3px}
.sk .c{width:26px;height:26px;border-radius:7px;background:var(--frame);display:grid;place-items:center;font-size:11px;font-weight:600}
.sk .c.on{background:var(--coral);color:#fff}
.sk .c.k{background:none;color:var(--muted);font-weight:700;font-size:13px}
.prio{font-size:14px;margin-bottom:10px;color:var(--muted)}
.prio b{color:var(--text);font-size:16px}
.runes{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.rs{display:grid;gap:8px}
.rs .h{display:flex;align-items:center;gap:8px;font-weight:600;font-size:14px}
.rs img,.rs .ph{width:28px;height:28px;border-radius:50%;background:rgba(0,0,0,.3)}
.rs .p{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted)}
.rs:first-child .p:nth-child(2) img{width:40px;height:40px}
.rs:first-child .p:nth-child(2){color:var(--text);font-weight:500}
.shards{font-size:12px;color:var(--faint);margin-top:12px}

/* eventos */
.events{grid-area:events}
.evs{display:grid;gap:4px;max-height:760px;overflow-y:auto;padding-right:6px}
.ev{display:grid;grid-template-columns:44px 10px minmax(0,1fr);align-items:center;gap:10px;padding:6px 8px;border-radius:12px;font-size:13px}
.ev.me{background:var(--card)}
.ev time{color:var(--muted);font-variant-numeric:tabular-nums;font-size:12px}
.ev i{width:10px;height:10px;border-radius:50%;background:var(--side)}
.ev .x{display:flex;align-items:center;gap:8px;min-width:0}
.ev .x img,.ev .x .ph{width:24px;height:24px;border-radius:7px;flex:none}
.ev .tag{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;padding:1px 7px;border-radius:8px;background:rgba(0,0,0,.3)}
.ev .tag.kill{color:var(--good)}.ev .tag.death{color:var(--bad)}.ev .tag.assist{color:var(--cream)}
.ally{--side:var(--ally)}.enemy{--side:var(--enemy)}
footer{grid-area:foot;font-size:12px;color:var(--faint);text-align:center}

@media (max-width:1180px){
  .prow{grid-template-columns:52px 24px 24px minmax(0,1fr) 96px 64px 222px}
  .prow .gold,.prow .dmg{display:none}
}
@media (max-width:1000px){
  .app{grid-template-columns:minmax(0,1fr);
    grid-template-areas:"top" "hero" "lane" "tiles" "chart" "obj" "board" "build" "events" "foot"}
  .tiles{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media (max-width:700px){
  body{padding:16px}
  .app{padding:16px;border-radius:30px;gap:20px}
  .hero{padding:24px;min-height:300px}
  .hero .art{inset:0}
  .hero::after{background:linear-gradient(180deg,color-mix(in srgb,var(--hero) 40%,transparent) 0%,var(--hero) 75%)}
  .hero h1{font-size:40px}
  .panel{padding:18px}
  .prow{grid-template-columns:46px minmax(0,1fr) 84px;gap:8px 10px}
  .prow .sp,.prow .cs,.prow.hd{display:none}
  .prow .items{grid-column:1/-1}
  .ch,.ch img,.ch .ph{width:42px;height:42px}
  .runes{grid-template-columns:1fr}
}
</style>
</head>
<body>
<div class="app">
  <header>
    <div class="greet" id="greet"></div>
    <div class="id" id="mid"></div>
  </header>
  <div class="hero" id="hero"></div>
  <section class="lane panel" id="lane"></section>
  <div class="tiles" id="tiles"></div>
  <section class="chart panel">
    <h2>Diferencia de oro <div class="tabs" id="tabs"></div></h2>
    <div id="chart"></div>
    <div class="key" id="ckey"></div>
  </section>
  <section class="obj panel" id="obj"></section>
  <section class="board" id="board"></section>
  <section class="build panel" id="build"></section>
  <section class="events panel" id="events"></section>
  <footer id="foot"></footer>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const DD = 'https://ddragon.leagueoflegends.com';
const ROLE = {TOP:'Top',JUNGLE:'Jungla',MIDDLE:'Mid',BOTTOM:'ADC',UTILITY:'Support','':'—'};
const KEYS = {1:'Q',2:'W',3:'E',4:'R'};
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = n => Number(n).toLocaleString('es-MX');
const signed = n => (n > 0 ? '+' : n < 0 ? '−' : '±') + num(Math.abs(n));
const short = n => { const a = Math.abs(n); return (n < 0 ? '−' : n > 0 ? '+' : '') + (a >= 1000 ? (a / 1000).toFixed(a % 1000 ? 1 : 0) + 'k' : a); };
const clock = ms => { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const P = Object.fromEntries(D.players.map(p => [p.id, p]));
const ME = D.players.find(p => p.me);
const RIVAL = D.rival ? P[D.rival] : null;
const side = team => team === ME.team ? 'ally' : 'enemy';

const url = {
  champ: id => id && D.ver ? `${DD}/cdn/${D.ver}/img/champion/${id}.png` : '',
  splash: id => id ? `${DD}/cdn/img/champion/splash/${id}_0.jpg` : '',
  item: id => id && D.ver ? `${DD}/cdn/${D.ver}/img/item/${id}.png` : '',
  spell: s => s.i && D.ver ? `${DD}/cdn/${D.ver}/img/spell/${s.i}.png` : '',
  rune: r => r.i ? `${DD}/cdn/img/${r.i}` : '',
};
const pic = (src, title = '', cls = '') => src
  ? `<img class="${cls}" src="${src}" alt="${esc(title)}" title="${esc(title)}" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'ph ${cls}'}))">`
  : `<span class="ph ${cls}" title="${esc(title)}"></span>`;
const champPic = p => pic(url.champ(p.cid), p.c);
const itemPic = (id, cls = '') => id ? pic(url.item(id), D.items[id] || '', cls) : `<span class="ph ${cls}"></span>`;

function renderHeader() {
  const m = D.match;
  $('#greet').innerHTML = `Tu última partida, <b>${esc(D.player.split('#')[0])}</b>`;
  $('#mid').textContent = `${m.id} · Ranked Solo/Duo`;
  $('#foot').textContent = `Generado el ${D.generated} · Datos de la API de Riot · Imágenes de Data Dragon ${D.ver || ''}`;
}

function renderHero() {
  const m = D.match;
  const [label, cls, hero] = m.remake ? ['Remake', 'neutral', 'remake'] : m.win ? ['Victoria', 'good', 'win'] : ['Derrota', 'bad', 'loss'];
  const date = new Date(m.t).toLocaleString('es-MX', {weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit'});
  const kda = ((ME.k + ME.a) / Math.max(1, ME.d)).toFixed(2);
  const el = $('#hero');
  el.className = 'hero ' + hero;
  el.innerHTML = `
    <div class="art" style="background-image:url('${url.splash(ME.cid)}')"></div>
    <div class="in">
      <div class="chips"><span class="res ${cls}">${label}</span><span class="chip">${ROLE[ME.pos]}</span>
        <span class="chip dark">${clock(m.d * 1000)}</span><span class="chip dark">Parche ${esc(m.patch)}</span></div>
      <h1>${esc(ME.c)}</h1>
      <div class="kda">${ME.k} / <span class="d">${ME.d}</span> / ${ME.a}<span class="r">${kda} KDA</span></div>
      <p>${esc(date)}${RIVAL ? ' · contra ' + esc(RIVAL.c) : ''}</p>
      <div class="badges">${D.badges.map(b => `<span class="badge">${esc(b)}</span>`).join('')}</div>
    </div>`;
}

function cmpRow(l, a, b, fmt = num) {
  const lead = a === b ? 0 : a > b ? 1 : -1;
  const tot = Math.max(1, Math.abs(a) + Math.abs(b));
  return `<div class="cmp"><div class="l">${esc(l)}</div>
    <div class="v ${lead > 0 ? 'lead' : ''}">${fmt(a)}</div>
    <div class="split" title="${esc(l)}: ${fmt(a)} vs ${fmt(b)}"><i class="a" style="flex:${Math.abs(a) / tot}"></i><i class="b" style="flex:${Math.abs(b) / tot}"></i></div>
    <div class="v b ${lead < 0 ? 'lead' : ''}">${fmt(b)}</div></div>`;
}

function renderLane() {
  const el = $('#lane');
  if (!RIVAL) { el.innerHTML = '<h2>Tu línea</h2><p class="empty">No se pudo identificar a tu rival de línea en esta partida.</p>'; return; }
  el.innerHTML = `<h2>Tú vs tu rival <small>${ROLE[ME.pos]}</small></h2>
    <div class="vs-head"><div class="who">${champPic(ME)}<span>${esc(ME.c)}</span></div>
      <div class="who r">${champPic(RIVAL)}<span>${esc(RIVAL.c)}</span></div></div>
    ${D.lane.map(r => cmpRow(r.l, r.a, r.b)).join('')}
    ${D.tl ? '' : '<p class="empty">Sin línea de tiempo: faltan los datos al minuto 10 y 15.</p>'}`;
}

function renderTiles() {
  $('#tiles').innerHTML = D.tiles.map(([l, v, s]) =>
    `<div class="tile"><div class="l">${esc(l)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join('');
}

const OBJ = [['tower', 'Torres'], ['inhibitor', 'Inhibidores'], ['dragon', 'Dragones'], ['horde', 'Larvas del Vacío'],
  ['riftHerald', 'Heraldo'], ['baron', 'Barón'], ['atakhan', 'Atakhan'], ['champion', 'Asesinatos']];
function renderObj() {
  const mine = D.teams[ME.team].obj, theirs = D.teams[ME.team === 100 ? 200 : 100].obj;
  $('#obj').innerHTML = `<h2>Objetivos</h2>
    <div class="vs-head"><div class="who ally"><span>Tu equipo</span></div><div class="who r"><span>Enemigo</span></div></div>
    ${OBJ.filter(([k]) => k in mine).map(([k, l]) => cmpRow(l, mine[k] || 0, theirs[k] || 0)).join('')}
    <div class="key"><span><i style="background:var(--ally)"></i>Tu equipo</span><span><i style="background:var(--enemy)"></i>Enemigo</span></div>`;
}

/* ── gráfica de oro ── */
const chart = {mode: 'team'};
function niceStep(ext) {
  const raw = ext / 2, pow = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map(f => f * pow).find(s => s >= raw);
}
function renderChart() {
  const box = $('#chart');
  if (!D.tl) {
    $('#tabs').innerHTML = '';
    box.innerHTML = '<p class="empty">No hay línea de tiempo para esta partida (se usó --sin-descargar o Riot no la devolvió).</p>';
    return;
  }
  const modes = [['team', 'Equipo']].concat(RIVAL ? [['lane', 'Vs ' + RIVAL.c]] : []);
  $('#tabs').innerHTML = modes.map(([k, l]) => `<button class="tab ${chart.mode === k ? 'on' : ''}" data-m="${k}">${esc(l)}</button>`).join('');
  const who = chart.mode === 'team' ? 'Tu equipo' : 'Tú';
  $('#ckey').innerHTML = `<span><i style="background:var(--ally)"></i>${who} va adelante</span>
    <span><i style="background:var(--enemy)"></i>${chart.mode === 'team' ? 'El enemigo' : esc(RIVAL?.c || '')} va adelante</span>`;

  const col = chart.mode === 'team' ? 1 : 2;
  const pts = D.tl.gold.map(r => [r[0], r[col]]);
  const W = Math.max(280, box.clientWidth), H = 260, L = 46, R = 12, T = 12, B = 28;
  const xmax = pts[pts.length - 1][0] || 1;
  const step = niceStep(Math.max(1000, ...pts.map(p => Math.abs(p[1]))));
  const ymax = Math.ceil(Math.max(1000, ...pts.map(p => Math.abs(p[1]))) / step) * step;
  const x = m => L + (W - L - R) * m / xmax;
  const y = v => T + (H - T - B) * (ymax - v) / (2 * ymax);
  const line = pts.map((p, i) => (i ? 'L' : 'M') + x(p[0]).toFixed(1) + ',' + y(p[1]).toFixed(1)).join('');
  const area = `${line}L${x(pts[pts.length - 1][0]).toFixed(1)},${y(0)}L${x(pts[0][0]).toFixed(1)},${y(0)}Z`;
  let grid = '';
  for (let v = -ymax; v <= ymax; v += step)
    grid += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" style="stroke:${v ? 'var(--grid)' : 'var(--muted)'};stroke-width:1"/>
             <text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${short(v)}</text>`;
  for (let m = 0; m <= xmax; m += 5)
    grid += `<text x="${x(m)}" y="${H - 6}" text-anchor="middle">${m}'</text>`;
  const zero = y(0);
  box.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="Diferencia de oro por minuto">
    <defs><clipPath id="cu"><rect x="0" y="0" width="${W}" height="${zero}"/></clipPath>
      <clipPath id="cd"><rect x="0" y="${zero}" width="${W}" height="${H}"/></clipPath></defs>
    ${grid}
    <path d="${area}" clip-path="url(#cu)" style="fill:var(--ally);fill-opacity:.22"/>
    <path d="${area}" clip-path="url(#cd)" style="fill:var(--enemy);fill-opacity:.3"/>
    <path d="${line}" clip-path="url(#cu)" style="fill:none;stroke:var(--ally);stroke-width:2;stroke-linejoin:round"/>
    <path d="${line}" clip-path="url(#cd)" style="fill:none;stroke:var(--enemy);stroke-width:2;stroke-linejoin:round"/>
    <g id="hov" style="display:none"><line id="hl" y1="${T}" y2="${H - B}" style="stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3"/>
      <circle id="hc" r="5" style="stroke:var(--panel);stroke-width:2"/></g>
    <rect id="hit" x="${L}" y="0" width="${W - L - R}" height="${H}" style="fill:transparent"/>
  </svg><div class="tip" id="tip"></div>`;

  const hit = $('#hit'), hov = $('#hov'), tip = $('#tip');
  const move = ev => {
    const r = hit.getBoundingClientRect();
    const m = (ev.clientX - r.left) / r.width * xmax;
    let i = 0;
    pts.forEach((p, j) => { if (Math.abs(p[0] - m) < Math.abs(pts[i][0] - m)) i = j; });
    const [pm, pv] = pts[i], px = x(pm), py = y(pv);
    hov.style.display = '';
    $('#hl').setAttribute('x1', px); $('#hl').setAttribute('x2', px);
    $('#hc').setAttribute('cx', px); $('#hc').setAttribute('cy', py);
    $('#hc').style.fill = pv >= 0 ? 'var(--ally)' : 'var(--enemy)';
    const ahead = pv > 0 ? `${who} va adelante` : pv < 0 ? (chart.mode === 'team' ? 'El enemigo va adelante' : `${RIVAL.c} va adelante`) : 'Empate';
    tip.innerHTML = `Minuto ${Math.round(pm)}<b>${signed(pv)} oro</b>${esc(ahead)}`;
    tip.style.display = 'block';
    const left = Math.min(px + 14, W - tip.offsetWidth - 4);
    tip.style.left = (px + 14 + tip.offsetWidth > W ? px - tip.offsetWidth - 14 : left) + 'px';
    tip.style.top = Math.max(0, Math.min(py - tip.offsetHeight / 2, H - tip.offsetHeight)) + 'px';
  };
  hit.addEventListener('pointermove', move);
  hit.addEventListener('pointerdown', move);
  hit.addEventListener('pointerleave', () => { hov.style.display = 'none'; tip.style.display = 'none'; });
}
$('#tabs').addEventListener('click', e => {
  const b = e.target.closest('[data-m]');
  if (b) { chart.mode = b.dataset.m; renderChart(); }
});
let resizeTimer;
window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderChart, 120); });

/* ── marcador ── */
function renderBoard() {
  const maxDmg = Math.max(1, ...D.players.map(p => p.dmg));
  const mins = D.match.d / 60;
  const teams = [ME.team, ME.team === 100 ? 200 : 100];
  $('#board').innerHTML = teams.map(team => {
    const t = D.teams[team], ps = D.players.filter(p => p.team === team);
    const k = ps.reduce((s, p) => s + p.k, 0), d = ps.reduce((s, p) => s + p.d, 0), a = ps.reduce((s, p) => s + p.a, 0);
    const gold = ps.reduce((s, p) => s + p.gold, 0);
    const rows = ps.map(p => `
      <div class="prow ${p.me ? 'me' : ''}">
        <div class="ch">${champPic(p)}<span class="lv">${p.lvl}</span></div>
        <div class="stk sp">${p.spells.map(s => pic(url.spell(s), s.n)).join('')}</div>
        <div class="stk sp">${pic(url.rune(p.ks), p.ks.n, 'rn')}${pic(url.rune(p.sub), p.sub.n, 'rn')}</div>
        <div class="nm"><b>${esc(p.name)}</b><span>#${esc(p.tag)} · ${esc(p.c)}</span></div>
        <div class="num">${p.k} / ${p.d} / ${p.a}<small>${((p.k + p.a) / Math.max(1, p.d)).toFixed(2)} KDA · ${p.kp}%</small></div>
        <div class="num cs">${p.cs}<small>${(p.cs / mins).toFixed(1)}/min</small></div>
        <div class="num gold">${(p.gold / 1000).toFixed(1)}k<small>oro</small></div>
        <div class="dmg">${num(p.dmg)}<div class="bar"><i style="width:${100 * p.dmg / maxDmg}%"></i></div></div>
        <div class="items">${p.items.slice(0, 6).map(i => itemPic(i)).join('')}${itemPic(p.items[6], 'tr')}</div>
      </div>`).join('');
    return `<div class="team ${side(team)}">
      <div class="team-h"><div class="t">${team === ME.team ? 'Tu equipo' : 'Equipo enemigo'} · ${t.win ? 'Victoria' : 'Derrota'}</div>
        <div class="tot">${k} / ${d} / ${a} · ${(gold / 1000).toFixed(1)}k de oro</div>
        <div class="bans">Bans ${t.bans.map(b => pic(url.champ(b.cid), b.c)).join('')}</div></div>
      <div class="rows">
        <div class="prow hd"><span>Campeón</span><span></span><span></span><span>Jugador</span><span>K / D / A</span>
          <span class="cs">CS</span><span class="gold">Oro</span><span class="dmg">Daño a campeones</span><span>Objetos</span></div>
        ${rows}</div></div>`;
  }).join('');
}

/* ── build, habilidades y runas ── */
function renderBuild() {
  let html = '<h2>Tu build</h2>';
  if (D.tl && D.tl.trips.length) {
    html += '<h3>Orden de compra</h3><div class="trips">' + D.tl.trips.map(([t, items], i) =>
      (i ? '<span class="arrow">›</span>' : '') +
      `<div class="trip"><div class="its">${items.map(id => itemPic(id)).join('')}</div><span>${clock(t)}</span></div>`).join('') + '</div>';
  } else {
    html += '<h3>Objetos finales</h3><div class="trips"><div class="trip"><div class="its">' +
      ME.items.filter(Boolean).map(id => itemPic(id)).join('') + '</div></div></div>';
  }
  if (D.tl && D.tl.skills.length) {
    const sk = D.tl.skills, count = {1: 0, 2: 0, 3: 0}, maxAt = {};
    sk.forEach((s, i) => { if (s < 4 && ++count[s] === 5) maxAt[s] = i; });
    const order = [1, 2, 3].sort((a, b) => (maxAt[a] ?? 99) - (maxAt[b] ?? 99) || count[b] - count[a]);
    html += `<h3>Habilidades</h3><div class="prio">Prioridad: <b>${order.map(s => KEYS[s]).join(' › ')}</b></div>
      <div class="skills"><div class="sk">${[1, 2, 3, 4].map(slot =>
        `<div class="r"><span class="c k">${KEYS[slot]}</span>${sk.map((s, i) =>
          `<span class="c ${s === slot ? 'on' : ''}">${s === slot ? i + 1 : ''}</span>`).join('')}</div>`).join('')}</div></div>`;
  }
  html += '<h3>Runas</h3><div class="runes">' + D.runes.styles.map(s =>
    `<div class="rs"><div class="h">${pic(url.rune(s.style), s.style.n)}${esc(s.style.n)}</div>${s.perks.map(r =>
      `<div class="p">${pic(url.rune(r), r.n)}${esc(r.n)}</div>`).join('')}</div>`).join('') + '</div>' +
    `<div class="shards">Fragmentos: ${D.runes.shards.map(esc).join(' · ')}</div>`;
  $('#build').innerHTML = html;
}

/* ── eventos ── */
function renderEvents() {
  const el = $('#events');
  if (!D.tl) { el.innerHTML = '<h2>Momentos clave</h2><p class="empty">Sin línea de tiempo para esta partida.</p>'; return; }
  const rows = D.tl.events.map(e => {
    let cls, me = false, body;
    if (e.k === 'kill') {
      cls = 'ally'; me = true;
      body = `<span class="tag kill">Kill</span>${champPic(P[e.b])}<span>Eliminaste a ${esc(P[e.b].c)}</span>`;
    } else if (e.k === 'death') {
      cls = 'enemy'; me = true;
      body = `<span class="tag death">Muerte</span>` + (P[e.a]
        ? `${champPic(P[e.a])}<span>Te eliminó ${esc(P[e.a].c)}</span>` : '<span>Moriste (ejecutado)</span>');
    } else if (e.k === 'assist') {
      cls = 'ally'; me = true;
      body = `<span class="tag assist">Asist.</span>${champPic(P[e.b])}<span>${P[e.a] ? esc(P[e.a].c) + ' eliminó a ' : 'Cayó '}${esc(P[e.b].c)}</span>`;
    } else if (e.k === 'obj') {
      cls = e.ally ? 'ally' : 'enemy';
      body = `<span>${e.ally ? 'Tu equipo' : 'El enemigo'} tomó <b>${esc(e.x)}</b>${e.n > 1 ? ' ×' + e.n : ''}</span>`;
    } else {
      cls = e.ally ? 'ally' : 'enemy';
      body = `<span>${e.ally ? 'Tu equipo destruyó' : 'El enemigo destruyó'} ${esc(e.x)}</span>`;
    }
    return `<div class="ev ${cls} ${me ? 'me' : ''}"><time>${clock(e.t)}</time><i></i><div class="x">${body}</div></div>`;
  }).join('');
  el.innerHTML = `<h2>Momentos clave <small>${D.tl.events.length} eventos</small></h2>
    <div class="key" style="margin:-6px 0 14px"><span><i style="background:var(--ally)"></i>A favor</span><span><i style="background:var(--enemy)"></i>En contra</span></div>
    <div class="evs">${rows}</div>`;
}

renderHeader(); renderHero(); renderLane(); renderTiles(); renderObj(); renderChart(); renderBoard(); renderBuild(); renderEvents();
</script>
</body>
</html>
"""
