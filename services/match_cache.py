import sqlite3
import json
import time
import os

# ======================================================
# DEFINIÇÃO DOS CAMINHOS DO BANCO
# ======================================================

# Caminho persistente no Railway
PERSISTENT_DIR = "/app/cache"
PERSISTENT_PATH = f"{PERSISTENT_DIR}/matches.db"

# Caminho local (pasta services/)
LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matches.db")

# Escolha do DB com fallback
if os.path.exists(PERSISTENT_PATH):
    DB_PATH = PERSISTENT_PATH
elif os.path.exists(LOCAL_PATH):
    DB_PATH = LOCAL_PATH
else:
    # Cria a pasta no Railway se não existe
    os.makedirs(PERSISTENT_DIR, exist_ok=True)
    DB_PATH = PERSISTENT_PATH


# ======================================================
# Inicialização do DB
# ======================================================
def init_matches_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS player_matches (
            puuid TEXT,
            match_id TEXT,
            PRIMARY KEY (puuid, match_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id TEXT PRIMARY KEY,
            json TEXT,
            timestamp INTEGER
        )
    """)

    conn.commit()
    conn.close()


# ======================================================
# SALVAR ID DE PARTIDA DO JOGADOR
# ======================================================
def save_player_match_id(puuid, match_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO player_matches (puuid, match_id) VALUES (?, ?)",
                  (puuid, match_id))
        conn.commit()
    finally:
        conn.close()


# ======================================================
# BUSCAR TODOS OS MATCH IDS DO JOGADOR
# ======================================================
def get_player_match_ids(puuid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT match_id FROM player_matches WHERE puuid = ?", (puuid,))
    rows = c.fetchall()
    conn.close()
    return {row[0] for row in rows}


# ======================================================
# SALVAR PARTIDA (JSON)
# ======================================================
def save_match_json(match_id, match_json):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO matches (match_id, json, timestamp)
        VALUES (?, ?, ?)
    """, (match_id, json.dumps(match_json), int(time.time())))
    conn.commit()
    conn.close()


# ======================================================
# CARREGAR PARTIDA DO CACHE
# ======================================================
def load_cached_match(match_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT json FROM matches WHERE match_id = ?", (match_id,))
    row = c.fetchone()
    conn.close()

    if row:
        return json.loads(row[0])
    return None


# ======================================================
# LIMPAR TODO CACHE DE UM JOGADOR
# ======================================================
def clear_player_cache(puuid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT match_id FROM player_matches WHERE puuid = ?", (puuid,))
    match_ids = [row[0] for row in c.fetchall()]

    c.execute("DELETE FROM player_matches WHERE puuid = ?", (puuid,))

    for mid in match_ids:
        c.execute("DELETE FROM matches WHERE match_id = ?", (mid,))

    conn.commit()
    conn.close()
