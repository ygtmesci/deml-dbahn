"""Connect to the team database (DuckDB behind a Postgres endpoint).

The connection string is DATABASE_URL, from the environment or from .env in the repo root.

    from src.db import query
    df = query("select * from val.questions limit 5")
"""
import os
from pathlib import Path

import pandas as pd
import psycopg

ENV = Path(__file__).resolve().parent.parent / ".env"


def url():
    if "DATABASE_URL" in os.environ:
        return os.environ["DATABASE_URL"]
    for line in ENV.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("DATABASE_URL is not set: add it to .env (link in the team chat)")


def connect():
    con = psycopg.connect(url(), autocommit=True)
    # Our plan has 512 MB, but DuckDB sees the host's memory; cap it so queries spill to disk instead
    con.execute("set memory_limit = '384MB'")
    con.execute("set threads = 2")
    return con


def query(sql, params=None):
    with connect() as con:
        cur = con.execute(sql, params)
        return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
