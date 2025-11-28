import psycopg2
import psycopg2.extras
import os
from urllib.parse import urlparse

def get_db_connection():
    db_url = os.getenv("DATABASE_URL")

    if not db_url:
        raise Exception("DATABASE_URL não encontrada!")

    result = urlparse(db_url)

    conn = psycopg2.connect(
        database=result.path[1:],   # remove a barra inicial
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )
    return conn


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            nickname TEXT NOT NULL,
            elo_solo TEXT NOT NULL,
            lp_solo INTEGER NOT NULL,
            elo_flex TEXT NOT NULL,
            lp_flex INTEGER NOT NULL,
            level INTEGER NOT NULL,
            icon TEXT NOT NULL,
            region TEXT NOT NULL,
            puuid TEXT NOT NULL UNIQUE,
            lane_primary TEXT,
            lane_secondary TEXT
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
