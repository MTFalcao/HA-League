from flask import (
    Flask, render_template, redirect, url_for, request,
    flash, session
)
import psycopg2
import psycopg2.extras
import unicodedata
import os
import requests
from dotenv import load_dotenv
load_dotenv()

from services.db import get_db_connection, init_db
from services.riot_api import (
    get_account_data, get_summoner_data_by_puuid,
    get_ranked_stats, load_ranked_matches,
    extract_history, extract_top_champs,
    calculate_player_stats, get_top3_masteries
)

from services.match_cache import init_matches_db, DB_PATH as MATCH_DB_PATH

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Inicializa banco
init_db()
init_matches_db()


# =====================================================
# SANITIZAÇÃO DE PUUID
# =====================================================
def limpar_unicode(texto):
    if not texto:
        return texto

    invis = [
        "\u200b", "\u200c", "\u200d", "\u200e", "\u200f",
        "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
        "\u2066", "\u2067", "\u2068", "\u2069"
    ]

    for c in invis:
        texto = texto.replace(c, "")

    texto = unicodedata.normalize("NFKC", texto)
    return texto.strip()


def validar_puuid(puuid):
    if not puuid:
        return puuid

    clean = limpar_unicode(puuid)
    clean = clean.replace(" ", "").replace("\n", "").replace("\r", "")

    if len(clean) != 78:
        print(f"⚠️ PUUID inválido detectado: {repr(puuid)} -> len={len(clean)}")

    return clean


def corrigir_puuids_no_banco():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT puuid FROM players")
    rows = cur.fetchall()

    for (original,) in rows:
        cleaned = validar_puuid(original)
        if cleaned != original:
            print("🔧 Corrigido PUUID:", repr(original), "->", repr(cleaned))
            cur.execute(
                "UPDATE players SET puuid=%s WHERE puuid=%s",
                (cleaned, original)
            )

    conn.commit()
    cur.close()
    conn.close()


corrigir_puuids_no_banco()


# =====================================================
# FUNÇÕES AUXILIARES
# =====================================================
def login_required(func):
    def wrapper(*args, **kwargs):
        if "admin" not in session:
            flash("Você precisa estar logado.", "error")
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


def get_all_players():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM players ORDER BY name ASC")
    data = cur.fetchall()
    cur.close()
    conn.close()
    return data


# Carrega lista de campeões apenas uma vez
champ_list = requests.get(
    "https://ddragon.leagueoflegends.com/cdn/14.1.1/data/en_US/champion.json"
).json()["data"]


def get_champion_name_by_id(champ_id):
    for champ in champ_list.values():
        if int(champ["key"]) == champ_id:
            return champ["id"]
    return None


@app.template_filter()
def format_pts(value):
    try:
        return f"{int(value):,}".replace(",", ".")
    except:
        return value
    
def get_inhouse_stats(player):
    discord_name = player.get("discord_name")

    if not discord_name:
        return {
            "wins": 0,
            "losses": 0,
            "mmr": 834,
            "wr": 0
        }

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT wins, losses, total_mmr, matches_played
        FROM inhouse_players
        WHERE discord_name = %s;
    """, (discord_name,))

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return {"wins": 0, "losses": 0, "mmr": 834, "wr": 0}

    wins = row["wins"]
    losses = row["losses"]
    total = row["matches_played"]
    mmr = row["total_mmr"] or 834
    wr = round((wins / total) * 100, 1) if total else 0

    return {
        "wins": wins,
        "losses": losses,
        "mmr": mmr,
        "wr": wr
    }

# =====================================================
# LOGIN
# =====================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":

        username = request.form["username"].strip()
        password = request.form["password"].strip()

        if username == os.getenv("ADMIN_USER") and password == os.getenv("ADMIN_PASS"):
            session["admin"] = True
            flash("Login realizado!", "success")
            return redirect(url_for("admin"))

        flash("Credenciais inválidas!", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("admin", None)
    flash("Sessão encerrada.", "info")
    return redirect(url_for("home"))




# =====================================================
# HOME
# =====================================================
@app.route("/")
def home():
    players = get_all_players()
    return render_template("home.html", players=players[:5])


# =====================================================
# LISTA DE JOGADORES
# =====================================================
@app.route("/jogadores")
def players():
    players = get_all_players()
    enriched = []

    for p in players:
        puuid = validar_puuid(p["puuid"])
        elo = get_ranked_stats(puuid)

        enriched.append({
            **p,
            "elo_solo": elo["solo_tier"],
            "lp_solo": elo["solo_lp"],
            "solo_wins": elo["solo_wins"],
            "solo_losses": elo["solo_losses"],
            "elo_flex": elo["flex_tier"],
            "lp_flex": elo["flex_lp"],
            "flex_wins": elo["flex_wins"],
            "flex_losses": elo["flex_losses"],
        })

    return render_template("players.html", players=enriched)


# =====================================================
# PERFIL DO JOGADOR
# =====================================================

@app.route("/player/<name>")
def player_profile(name):

    # Buscar player do banco
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM players WHERE name=%s", (name,))
    player = cur.fetchone()
    cur.close()
    conn.close()

    if not player:
        flash("Jogador não encontrado!", "error")
        return redirect(url_for("players"))

    puuid = validar_puuid(player["puuid"])

    # ================================
    # 1) Buscar RANK ATUAL direto da API
    # ================================
    elo = get_ranked_stats(puuid)

    # Aplicar no objeto "player"
    player["elo_solo"] = elo["solo_tier"]
    player["lp_solo"] = elo["solo_lp"]
    player["solo_wins"] = elo["solo_wins"]
    player["solo_losses"] = elo["solo_losses"]

    player["elo_flex"] = elo["flex_tier"]
    player["lp_flex"] = elo["flex_lp"]
    player["flex_wins"] = elo["flex_wins"]
    player["flex_losses"] = elo["flex_losses"]

    # Winrates
    solo_total = elo["solo_wins"] + elo["solo_losses"]
    wr_solo = round(elo["solo_wins"] / solo_total * 100, 1) if solo_total else 0

    flex_total = elo["flex_wins"] + elo["flex_losses"]
    wr_flex = round(elo["flex_wins"] / flex_total * 100, 1) if flex_total else 0

    # ================================
    # 2) Histórico, Top Champs e Stats
    # ================================
    matches = load_ranked_matches(puuid, count=50)
    history = extract_history(puuid, matches, limit=10)
    stats = calculate_player_stats(history)
    top_champs = extract_top_champs(puuid, matches)

    # ================================
    # 3) Top 3 Maestrias
    # ================================
    top3 = get_top3_masteries(puuid)
    if top3:
        for m in top3:
            champ_key = get_champion_name_by_id(m["championId"])
            m["championName"] = champ_key

    # ================================
    # 4) Estatísticas do Inhouse
    # ================================
    inhouse_stats = get_inhouse_stats(player)

    # ================================
    # Renderização final
    # ================================
    return render_template(
        "player_profile.html",
        player=player,
        history=history,
        stats=stats,
        wr_solo=wr_solo,
        wr_flex=wr_flex,
        top_champs=top_champs,
        top3=top3,
        inhouse_stats=inhouse_stats
    )


# =====================================================
# REFRESH
# =====================================================
@app.route("/refresh/<puuid>")
def refresh_player_history(puuid):
    puuid = validar_puuid(puuid)

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT name FROM players WHERE puuid=%s", (puuid,))
    player = cur.fetchone()
    cur.close()
    conn.close()

    if not player:
        flash("Jogador não encontrado!", "error")
        return redirect(url_for("players"))

    load_ranked_matches(puuid, count=50)

    flash("Histórico atualizado!", "success")
    return redirect(url_for("player_profile", name=player["name"]))

# =====================================================
# RANK GERAL DO INHOUSE
# =====================================================
@app.route("/ranking")
def ranking():

    order = request.args.get("order", "mmr")  # padrão MMR

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT * FROM players")
    players = cur.fetchall()
    cur.close()
    conn.close()

    enriched = []

    for p in players:
        stats = get_inhouse_stats(p)

        enriched.append({
            **p,
            "inhouse": stats,
        })

    if order == "wr":
        enriched.sort(key=lambda x: x["inhouse"]["wr"], reverse=True)
    elif order == "wins":
        enriched.sort(key=lambda x: x["inhouse"]["wins"], reverse=True)
    else:  # MMR
        enriched.sort(key=lambda x: x["inhouse"]["mmr"], reverse=True)

    return render_template("inhouse_ranking.html", players=enriched, order=order)


# =====================================================
# PAINEL ADMIN
# =====================================================
@app.route("/admin")
@login_required
def admin():
    players = get_all_players()
    return render_template("admin_panel.html", players=players)


# =====================================================
# REMOVER JOGADOR
# =====================================================
@app.route("/admin/delete/<nickname>", methods=["POST"])
@login_required
def delete_player(nickname):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM players WHERE nickname=%s", (nickname,))
    conn.commit()
    cur.close()
    conn.close()

    flash("Jogador removido!", "success")
    return redirect(url_for("admin"))


# =====================================================
# EDITAR JOGADOR
# =====================================================
@app.route("/admin/edit/<nickname>", methods=["GET", "POST"])
@login_required
def edit_player(nickname):

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # pega player no site
    cur.execute("SELECT * FROM players WHERE nickname=%s", (nickname,))
    player = cur.fetchone()

    if not player:
        flash("Jogador não encontrado!", "error")
        return redirect(url_for("admin"))

    # pega dados inhouse agregados
    cur.execute("""
        SELECT wins, losses, total_mmr, matches_played
        FROM inhouse_players
        WHERE discord_name = %s
    """, (player.get("discord_name"),))
    ih = cur.fetchone()

    ih_data = {
        "wins": ih["wins"] if ih else 0,
        "losses": ih["losses"] if ih else 0,
        "mmr": ih["total_mmr"] if ih else 834,
        "matches": ih["matches_played"] if ih else 0
    }

    if request.method == "POST":

        new_nickname = request.form.get("nickname")
        new_lane_primary = request.form.get("lane_primary")
        new_lane_secondary = request.form.get("lane_secondary")
        new_discord = request.form.get("discord_name")

        wins = int(request.form.get("wins"))
        losses = int(request.form.get("losses"))
        mmr = int(request.form.get("total_mmr"))
        matches = int(request.form.get("matches_played"))

        # atualizar tabela players
        cur.execute("""
            UPDATE players
            SET nickname=%s, lane_primary=%s, lane_secondary=%s, discord_name=%s
            WHERE puuid=%s
        """, (
            new_nickname,
            new_lane_primary,
            new_lane_secondary,
            new_discord,
            player["puuid"]
        ))

        # atualizar tabela inhouse_players
        cur.execute("""
            INSERT INTO inhouse_players (discord_name, wins, losses, total_mmr, matches_played)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (discord_name) DO UPDATE SET
                wins = EXCLUDED.wins,
                losses = EXCLUDED.losses,
                total_mmr = EXCLUDED.total_mmr,
                matches_played = EXCLUDED.matches_played;
        """, (new_discord, wins, losses, mmr, matches))

        conn.commit()
        cur.close()
        conn.close()

        flash("Jogador atualizado!", "success")
        return redirect(url_for("admin"))

    cur.close()
    conn.close()
    return render_template("edit_player.html", player=player, inhouse=ih_data)



# =====================================================
# CADASTRAR (ADMIN)
# =====================================================
@app.route("/cadastrar", methods=["GET", "POST"])
@login_required
def cadastrar():

    if request.method == "POST":

        riot_tag = limpar_unicode(request.form["summoner_name"])

        if "#" not in riot_tag:
            flash("Formato inválido.", "error")
            return redirect(url_for("cadastrar"))

        account = get_account_data(riot_tag)
        if not account:
            flash("Riot ID não encontrado!", "error")
            return redirect(url_for("cadastrar"))

        puuid = validar_puuid(account["puuid"])
        gameName = account["gameName"]
        tagLine = account["tagLine"]

        summoner = get_summoner_data_by_puuid(puuid)
        elo = get_ranked_stats(puuid)

        # fallback seguro
        icon_id = summoner.get("profileIconId") or 1
        icon_url = f"https://ddragon.leagueoflegends.com/cdn/15.23.1/img/profileicon/{icon_id}.png"

        lane_primary = request.form.get("lane_primary")
        lane_secondary = request.form.get("lane_secondary")

        # NOVO: captura do Discord Name / ID
        discord_name = request.form.get("discord_name") or None

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                INSERT INTO players (
                    name, nickname, elo_solo, lp_solo,
                    elo_flex, lp_flex, level, icon,
                    region, puuid, lane_primary, lane_secondary,
                    discord_name
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                gameName,
                f"{gameName}#{tagLine}",
                elo["solo_tier"], elo["solo_lp"],
                elo["flex_tier"], elo["flex_lp"],
                summoner["summonerLevel"],
                icon_url,
                "br1",
                puuid,
                lane_primary,
                lane_secondary,
                discord_name
            ))
            conn.commit()

        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            flash("Jogador já existe!", "warning")

        finally:
            cur.close()
            conn.close()

        flash("Cadastrado!", "success")
        return redirect(url_for("admin"))

    return render_template("admin_add.html")

# =====================================================
# TESTE DA API DA RIOT
# =====================================================
@app.route("/admin/test_riot")
@login_required
def test_riot():
    from services.riot_api import API_KEY

    riot_id = "Jolene#BR2"

    account = get_account_data(riot_id)
    if not account:
        return {"ok": False, "message": "Erro ao buscar Riot ID"}

    puuid = account["puuid"]
    summoner = get_summoner_data_by_puuid(puuid)
    ranked = get_ranked_stats(puuid)

    return {
        "ok": True,
        "riot_id": riot_id,
        "api_key_prefix": API_KEY[:12] + "...",
        "puuid": puuid,
        "summoner": summoner,
        "ranked": ranked
    }


# =====================================================
# RUN
# =====================================================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
