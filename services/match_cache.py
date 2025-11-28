import sqlite3
import json
import time
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # /services
ROOT = os.path.dirname(BASE_DIR)                       # /
DB_PATH = os.path.join(ROOT, "data", "matches.db")

# ======================================================
# Inicialização do DB
# ======================================================
def init_matches_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Tabela: Lista de partidas de cada jogador
    c.execute("""
        CREATE TABLE IF NOT EXISTS player_matches (
            puuid TEXT,
            match_id TEXT,
            PRIMARY KEY (puuid, match_id)
        )
    """)

    # Tabela: JSON das partidas completas
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
# LIMPAR TODO CACHE DE UM JOGADOR (para botão refresh)
# ======================================================
def clear_player_cache(puuid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Pegar todos os match_ids desse jogador
    c.execute("SELECT match_id FROM player_matches WHERE puuid = ?", (puuid,))
    match_ids = [row[0] for row in c.fetchall()]

    # Apagar do player_matches
    c.execute("DELETE FROM player_matches WHERE puuid = ?", (puuid,))

    # Apagar JSON das partidas
    for mid in match_ids:
        c.execute("DELETE FROM matches WHERE match_id = ?", (mid,))

    conn.commit()
    conn.close()
