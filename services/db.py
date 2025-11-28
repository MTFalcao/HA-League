import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    # Tenta usar DATABASE_URL (Railway / produção)
    DATABASE_URL = os.getenv("DATABASE_URL")

    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL, sslmode="require")

    # Se não tiver DATABASE_URL, usa as variáveis locais
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        port=os.getenv("POSTGRES_PORT")
    )

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
