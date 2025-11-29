from flask import (
    Flask, render_template, redirect, url_for, request,
    flash, session
)
import psycopg2
import psycopg2.extras
import unicodedata
import os
import requests

from services.db import get_db_connection, init_db
from services.riot_api import (
    get_account_data, get_summoner_data_by_puuid,
    get_ranked_stats, load_ranked_matches,
    extract_history, extract_top_champs,
    calculate_player_stats,get_top3_masteries
)

from services.match_cache import init_matches_db, DB_PATH as MATCH_DB_PATH
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Inicializar PostgreSQL e cache SQLite
init_db()
init_matches_db()


# =====================================================
# SANITIZAÇÃO DE PUUID + VALIDADOR
# =====================================================

def limpar_unicode(texto):
    if not texto:
        return texto

    invis = ["\u200b", "\u200c", "\u200d", "\u200e", "\u200f",
             "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
             "\u2066", "\u2067", "\u2068", "\u2069"]

    for c in invis:
        texto = texto.replace(c, "")

    texto = unicodedata.normalize("NFKC", texto)
    return texto.strip()


def validar_puuid(puuid):
    """Retorna o PUUID limpo, padronizado e válido (78 chars)."""
    if not puuid:
        return puuid

    clean = limpar_unicode(puuid)

    # Corrigir se veio com espaços/quebras
    clean = clean.replace(" ", "").replace("\n", "").replace("\r", "")

    # Tamanho do PUUID da Riot = 78
    if len(clean) != 78:
        print(f"⚠️ PUUID inválido detectado: {repr(puuid)} -> len={len(clean)}")
    return clean


def corrigir_puuids_no_banco():
    """Limpa silenciosamente todos os PUUIDs contaminados existentes no PostgreSQL."""
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


# Corrige todos os PUUIDs sempre ao iniciar servidor
corrigir_puuids_no_banco()


# =====================================================
# FUNÇÕES AUXILIARES
# =====================================================
def login_required(func):
    def wrapper(*args, **kwargs):
        if "admin" not in session:
            flash("Você precisa estar logado para acessar isso.", "error")
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


# Carrega lista de campeões 1 vez
champ_list = requests.get(
    "https://ddragon.leagueoflegends.com/cdn/14.1.1/data/en_US/champion.json"
).json()["data"]

def get_champion_name_by_id(champ_id):
    for champ in champ_list.values():
        if int(champ["key"]) == champ_id:
            return champ["id"]   # Ex: "Yasuo"
    return None


@app.template_filter()
def format_pts(value):
    try:
        return f"{int(value):,}".replace(",", ".")
    except:
        return value


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
# PAINEL ADMIN
# =====================================================

@app.route("/admin")
@login_required
def admin():
    players = get_all_players()
    return render_template("admin_panel.html", players=players)


# =====================================================
# APAGAR JOGADOR
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
    cur.execute("SELECT * FROM players WHERE nickname=%s", (nickname,))
    player = cur.fetchone()

    if not player:
        flash("Jogador não encontrado!", "error")
        return redirect(url_for("admin"))

    if request.method == "POST":

        new_lane_primary = request.form.get("lane_primary")
        new_lane_secondary = request.form.get("lane_secondary")
        new_nickname = request.form.get("nickname")

        cur.execute("""
            UPDATE players
            SET nickname=%s,
                lane_primary=%s,
                lane_secondary=%s
            WHERE puuid=%s
        """, (new_nickname, new_lane_primary, new_lane_secondary, player["puuid"]))

        conn.commit()
        cur.close()
        conn.close()

        flash("Jogador atualizado!", "success")
        return redirect(url_for("admin"))

    cur.close()
    conn.close()
    return render_template("edit_player.html", player=player)

# =====================================================
# PERFIL DO JOGADOR
# =====================================================

@app.route("/player/<name>")
def player_profile(name):

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

    # ============================
    #  RANQUEADAS
    # ============================
    elo = get_ranked_stats(puuid)

    solo_total = elo["solo_wins"] + elo["solo_losses"]
    wr_solo = round(elo["solo_wins"] / solo_total * 100, 1) if solo_total else 0

    flex_total = elo["flex_wins"] + elo["flex_losses"]
    wr_flex = round(elo["flex_wins"] / flex_total * 100, 1) if flex_total else 0

    # ============================
    #  PARTIDAS
    # ============================
    matches = load_ranked_matches(puuid, count=50)
    history = extract_history(puuid, matches, limit=10)
    stats = calculate_player_stats(history)
    top_champs = extract_top_champs(puuid, matches)

    # ============================
    #  TOP 3 MAESTRIAS
    # ============================
    top3 = get_top3_masteries(puuid)


    if top3:
        for m in top3:
            champ_key = get_champion_name_by_id(m["championId"])
            m["championName"] = champ_key  # usado no ícone

    return render_template("player_profile.html",
                           player=player,
                           history=history,
                           stats=stats,
                           wr_solo=wr_solo,
                           wr_flex=wr_flex,
                           top_champs=top_champs,
                           top3=top3)


@app.route("/refresh/<puuid>")
def refresh_player_history(puuid):
    puuid = validar_puuid(puuid)

    # 1. identificar nome do jogador
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT name FROM players WHERE puuid=%s", (puuid,))
    player = cur.fetchone()
    cur.close()
    conn.close()

    if not player:
        flash("Jogador não encontrado!", "error")
        return redirect(url_for("players"))

    # 2. carregar apenas partidas novas
    matches = load_ranked_matches(puuid, count=50)

    flash("Histórico foi atualizado com partidas novas!", "success")

    return redirect(url_for("player_profile", name=player["name"]))


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

        icon_url = f"https://ddragon.leagueoflegends.com/cdn/15.23.1/img/profileicon/{summoner['profileIconId']}.png"

        lane_primary = request.form.get("lane_primary")
        lane_secondary = request.form.get("lane_secondary")

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                INSERT INTO players (
                    name, nickname, elo_solo, lp_solo,
                    elo_flex, lp_flex, level, icon,
                    region, puuid, lane_primary, lane_secondary
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                lane_secondary
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
# RUN
# =====================================================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True
    )
