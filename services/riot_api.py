import requests
import os
from dotenv import load_dotenv

load_dotenv()

from services.match_cache import (
    save_player_match_id,
    get_player_match_ids,
    save_match_json,
    load_cached_match
)

API_KEY = os.getenv("RIOT_API_KEY")

# ============================================================
# 1) Buscar conta pelo Riot ID (gameName#Tag)
# ============================================================
def get_account_data(riot_id):
    try:
        gameName, tagLine = riot_id.strip().split("#")
    except:
        return None

    url = (
        f"https://americas.api.riotgames.com/riot/account/v1/accounts/"
        f"by-riot-id/{gameName}/{tagLine}"
    )
    r = requests.get(url, headers={"X-Riot-Token": API_KEY})
    return r.json() if r.status_code == 200 else None


# ============================================================
# 2) Buscar Summoner pelo PUUID (compatível com Personal Key)
# ============================================================
def get_summoner_data_by_puuid(puuid):
    url = f"https://br1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
    headers = {"X-Riot-Token": API_KEY}

    r = requests.get(url, headers=headers)
    
    # Summoner V4 falha com personal key em campos criptografados
    if r.status_code != 200:
        return {
            "profileIconId": 1,
            "summonerLevel": 0,
            "puuid": puuid,
            "name": None,       
        }

    data = r.json()

    # Nome pode ser None — isso é esperado com Personal Key
    return {
        "name": data.get("name"),
        "profileIconId": data.get("profileIconId"),
        "summonerLevel": data.get("summonerLevel"),
        "puuid": data.get("puuid"),
    }


# ============================================================
# 3) Rank Solo/Duo e Flex (funciona com Personal Key)
# ============================================================
def get_ranked_stats(puuid):
    url = f"https://br1.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
    r = requests.get(url, headers={"X-Riot-Token": API_KEY})

    if r.status_code != 200:
        return {
            "solo_tier": "UNRANKED",
            "solo_lp": 0,
            "solo_wins": 0,
            "solo_losses": 0,
            "flex_tier": "UNRANKED",
            "flex_lp": 0,
            "flex_wins": 0,
            "flex_losses": 0,
        }

    solo_tier, solo_lp, solo_wins, solo_losses = "UNRANKED", 0, 0, 0
    flex_tier, flex_lp, flex_wins, flex_losses = "UNRANKED", 0, 0, 0

    for entry in r.json():
        if entry["queueType"] == "RANKED_SOLO_5x5":
            solo_tier = f"{entry['tier']} {entry['rank']}"
            solo_lp = entry["leaguePoints"]
            solo_wins = entry["wins"]
            solo_losses = entry["losses"]

        elif entry["queueType"] == "RANKED_FLEX_SR":
            flex_tier = f"{entry['tier']} {entry['rank']}"
            flex_lp = entry["leaguePoints"]
            flex_wins = entry["wins"]
            flex_losses = entry["losses"]

    return {
        "solo_tier": solo_tier,
        "solo_lp": solo_lp,
        "solo_wins": solo_wins,
        "solo_losses": solo_losses,
        "flex_tier": flex_tier,
        "flex_lp": flex_lp,
        "flex_wins": flex_wins,
        "flex_losses": flex_losses,
    }


# ============================================================
# 4) Carregar partidas
# ============================================================
def load_ranked_matches(puuid, count=50):

    match_ids = []

    url_420 = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=420&start=0&count={count}"
    url_440 = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?queue=440&start=0&count={count}"

    for url in [url_420, url_440]:
        r = requests.get(url, headers={"X-Riot-Token": API_KEY})
        if r.status_code == 200:
            match_ids += r.json()

    match_ids = list(dict.fromkeys(match_ids))

    cached_ids = get_player_match_ids(puuid)
    matches = []

    for match_id in match_ids:
        save_player_match_id(puuid, match_id)

        cached_match = load_cached_match(match_id)
        if cached_match:
            matches.append(cached_match)
            continue

        url = f"https://americas.api.riotgames.com/lol/match/v5/matches/{match_id}"
        r = requests.get(url, headers={"X-Riot-Token": API_KEY})

        if r.status_code == 200:
            match_json = r.json()
            save_match_json(match_id, match_json)
            matches.append(match_json)

    return matches

# ============================================================
# 5) Parse OP.GG style
# ============================================================
def parse_match(puuid, match_json):
    info = match_json["info"]

    participant = None
    for p in info["participants"]:
        if p["puuid"] == puuid:
            participant = p
            break

    if not participant:
        return None

    duration = info["gameDuration"]
    mm = duration // 60
    ss = duration % 60

    return {
        "champion": participant["championName"],
        "lane": participant.get("teamPosition", "UNKNOWN").upper(),
        "kills": participant["kills"],
        "deaths": participant["deaths"],
        "assists": participant["assists"],
        "cs": participant["totalMinionsKilled"] + participant["neutralMinionsKilled"],
        "gold": participant["goldEarned"],
        "duration": f"{mm}:{ss:02d}",
        "result": "WIN" if participant["win"] else "LOSS",
    }


# ============================================================
# 6) Histórico e Top Champs usando MESMOS dados
# ============================================================
def extract_history(puuid, matches, limit=10):
    parsed = []
    for m in matches:
        p = parse_match(puuid, m)
        if p:
            parsed.append(p)
    return parsed[:limit]


def extract_top_champs(puuid, matches):
    champions = {}

    for match in matches:
        info = match["info"]

        participant = None
        for p in info["participants"]:
            if p["puuid"] == puuid:
                participant = p
                break

        if not participant:
            continue

        champ = participant["championName"]

        if champ not in champions:
            champions[champ] = {
                "games": 0,
                "wins": 0,
                "kills": 0,
                "deaths": 0,
                "assists": 0,
            }

        c = champions[champ]
        c["games"] += 1
        c["wins"] += 1 if participant["win"] else 0
        c["kills"] += participant["kills"]
        c["deaths"] += participant["deaths"]
        c["assists"] += participant["assists"]

    # montar lista final
    result = []
    for champ, data in champions.items():
        deaths = data["deaths"]
        kda = "∞" if deaths == 0 else round((data["kills"] + data["assists"]) / deaths, 2)

        result.append({
            "champion": champ,
            "games": data["games"],
            "winrate": round((data["wins"] / data["games"]) * 100, 1),
            "kda": kda,
        })

    # ordenar por jogos
    result.sort(key=lambda x: x["games"], reverse=True)

    return result[:5]


# ============================================================
# 7) Estatísticas gerais
# ============================================================
def calculate_player_stats(history):
    if not history:
        return {"total_games": 0, "wins": 0, "losses": 0, "winrate": 0, "kda_avg": 0}

    total_games = len(history)
    wins = sum(1 for m in history if m["result"] == "WIN")
    losses = total_games - wins

    kills = sum(m["kills"] for m in history)
    deaths = sum(m["deaths"] for m in history)
    assists = sum(m["assists"] for m in history)

    winrate = round((wins / total_games) * 100, 1)
    kda = (kills + assists) / deaths if deaths > 0 else (kills + assists)

    return {
        "total_games": total_games,
        "wins": wins,
        "losses": losses,
        "winrate": winrate,
        "kda_avg": round(kda, 2),
    }

# ============================================================
# 7) Maestria de Campeões
# ============================================================

def get_top3_masteries(puuid, region="br1"):
    url = f"https://{region}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
    r = requests.get(url, headers={"X-Riot-Token": API_KEY})

    if r.status_code != 200:
        return None

    data = r.json()
    return data[:3]  # Só as 3 maiores
