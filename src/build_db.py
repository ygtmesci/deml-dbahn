"""Build the team database from the raw course data in data/.

    .venv/bin/python src/build_db.py          # parse data/ into data/processed/dbahn.duckdb, then upload
    .venv/bin/python src/build_db.py upload   # upload data/processed/dbahn.duckdb only
    .venv/bin/python src/build_db.py upload val.changes val.messages   # upload some tables only

Only needed when new raw data arrives (e.g. the test split); everyone else reads the database.
"""
import json
import sys
import tarfile
import tempfile
import zipfile
from multiprocessing import Pool
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa

import db
import parse
import schema

DATA = parse.DATA
SCORING = DATA.parent / "scoring"
LOCAL = DATA / "processed" / "dbahn.duckdb"
SQL_TYPES = {"string": "VARCHAR", "datetime64[ns]": "TIMESTAMP", "Int64": "BIGINT",
             "float64": "DOUBLE", "boolean": "BOOLEAN"}
# folder in weather.tar -> (DWD column, our column)
WEATHER_VARS = {"air_temperature": ("TT_10", "temperature_c"),
                "precipitation": ("RWS_10", "precip_mm"),
                "wind": ("FF_10", "wind_ms")}
UPLOAD_BATCH_ROWS = 50_000
WEATHER_FROM_UTC ="202610272300"  # 28 Oct 00:00 local, start of the training data


def create(con, name, cols):
    con.execute(f"create or replace table {name} ({', '.join(f'{c} {SQL_TYPES[t]}' for c, t in cols.items())})")


def insert(con, name, cols, rows):
    """Insert rows of raw strings, converting times and integers to the schema types."""
    if not rows:
        return
    batch = pa.table({c: pa.array(v, pa.string()) for c, v in zip(cols, zip(*rows))})
    exprs = []
    for c, t in cols.items():
        if t == "datetime64[ns]":
            fmt = "%Y%m%d_%H%M%S" if c == "snapshot_time" else "%y%m%d%H%M"
            exprs.append(f"strptime({c}, '{fmt}')")
        elif t == "Int64":
            exprs.append(f"cast({c} as bigint)")
        else:
            exprs.append(c)
    con.execute(f"insert into {name} select {', '.join(exprs)} from batch")


def new_rows(rows, prev, key):
    """Rows that were not in the previous snapshot with the same values, and this snapshot's state."""
    cur = {key(r): r[1:] for r in rows}
    return [r for r in rows if prev.get(key(r)) != r[1:]], cur


def _plan(args):
    return parse.parse_plan(*args)


def _fchg(args):
    return parse.parse_fchg(*args)


def build_timetables(con, split):
    con.execute(f"create schema if not exists {split}")
    for t, cols in (("planned_stops", schema.PLANNED_STOPS), ("changes", schema.CHANGES),
                    ("messages", schema.MESSAGES)):
        create(con, f"{split}.{t}", cols)
    with Pool() as pool:
        prev = {}
        for rows in pool.imap(_plan, [(split, n, s) for n, s in parse.snapshots(split, "plan")]):
            rows, prev = new_rows(rows, prev, lambda r: (r[1], r[4]))  # s_id, eva
            insert(con, f"{split}.planned_stops", schema.PLANNED_STOPS, rows)
        snaps = [(split, n, s) for n, s in parse.snapshots(split, "fchg")]
        prev_c, prev_m = {}, {}
        for i, (changes, messages) in enumerate(pool.imap(_fchg, snaps), 1):
            changes, prev_c = new_rows(changes, prev_c, lambda r: (r[1], r[2]))  # s_id, eva
            messages, prev_m = new_rows(messages, prev_m, lambda r: r[1:])
            insert(con, f"{split}.changes", schema.CHANGES, changes)
            insert(con, f"{split}.messages", schema.MESSAGES, messages)
            if i % 100 == 0:
                print(f"  {split} fchg {i}/{len(snaps)}", flush=True)


def build_questions(con, split):
    questions, answers = DATA / f"{split}_questions.csv", SCORING / f"{split}_answers.csv"
    if not questions.exists():
        return
    create(con, f"{split}.questions", schema.QUESTIONS)
    labels = (f"read_csv('{answers}', all_varchar=true)" if answers.exists() else
              "(select null question_id, null train_group, null planned, null actual, null delay_min)")
    con.execute(f"""
        insert into {split}.questions
        select q.question_id, strptime(q.now, '%y%m%d%H%M'), q.last_stop_s_id, cast(q.horizon as bigint),
               q.target_s_id, q.target_station, a.train_group, strptime(a.planned, '%y%m%d%H%M'),
               strptime(a.actual, '%y%m%d%H%M'), cast(a.delay_min as double)
        from read_csv('{questions}', all_varchar=true) q left join {labels} a using (question_id)""")


def build_stations(con):
    rows = []
    for s in json.loads((DATA / "stations.json").read_text())["result"]:
        for e in s.get("evaNumbers", []):
            lon, lat = e.get("geographicCoordinates", {}).get("coordinates", (None, None))
            rows.append((str(e["number"]), s["name"], lat, lon, s.get("category"), s.get("federalState"),
                         e.get("isMain")))
    df = pd.DataFrame(rows, columns=list(schema.STATIONS)).astype(schema.STATIONS)
    create(con, "main.stations", schema.STATIONS)
    con.execute("insert into main.stations select * from df")


def build_weather(con):
    readings = {v: [] for v in WEATHER_VARS}
    dwd = {}
    with tarfile.open(DATA / "weather.tar") as t:
        for m in t:
            var, name = Path(m.name).parent.name, Path(m.name).name
            if not m.isfile() or var not in WEATHER_VARS:
                continue
            if "Beschreibung_Stationen" in name:
                for line in t.extractfile(m).read().decode("latin1").splitlines()[2:]:
                    f = line.split()
                    if f:
                        dwd[f[0]] = (f[0], float(f[4]), float(f[5]))
                continue
            if name.endswith(".zip"):
                with zipfile.ZipFile(t.extractfile(m)) as z:
                    texts = [z.read(n).decode("latin1") for n in z.namelist() if n.startswith("produkt")]
            elif name.startswith("produkt"):  # loose files next to the zips
                texts = [t.extractfile(m).read().decode("latin1")]
            else:
                continue
            for text in texts:
                lines = text.splitlines()
                i = [h.strip() for h in lines[0].split(";")].index(WEATHER_VARS[var][0])
                for line in lines[1:]:
                    f = [x.strip() for x in line.split(";")]
                    if f[1] >= WEATHER_FROM_UTC:
                        readings[var].append((f[0].zfill(5), f[1], f[i]))

    for var, (_, col) in WEATHER_VARS.items():
        df = pd.DataFrame(readings[var], columns=["dwd_id", "t", "v"])
        # train and val archives overlap on 3 Nov and one file is duplicated, so keep one row per slot
        con.execute(f"""
            create or replace temp table w_{var} as
            select dwd_id, strptime(t, '%Y%m%d%H%M') + interval 1 hour as time,
                   max(nullif(cast(v as double), -999)) as {col},
                   count(distinct v) as n_values
            from df group by all""")
        conflicts = con.execute(f"select count(*) from w_{var} where n_values > 1").fetchone()[0]
        if conflicts:
            print(f"  weather {var}: {conflicts} slots with differing values, kept the max")
    create(con, "main.weather", schema.WEATHER)
    con.execute("""
        insert into main.weather
        select dwd_id, time, temperature_c, precip_mm, wind_ms
        from w_air_temperature full join w_precipitation using (dwd_id, time) full join w_wind using (dwd_id, time)""")

    dwd_df = pd.DataFrame(dwd.values(), columns=["dwd_id", "lat", "lon"])
    create(con, "main.station_weather", schema.STATION_WEATHER)
    con.execute("""
        insert into main.station_weather
        with candidates as (
            select d.* from dwd_df d join (
                select dwd_id from main.weather group by dwd_id
                having count(temperature_c) > 0 and count(precip_mm) > 0 and count(wind_ms) > 0
            ) using (dwd_id)),
        pairs as (
            select s.eva, c.dwd_id,
                   2 * 6371 * asin(sqrt(sin(radians(c.lat - s.lat) / 2) ^ 2
                       + cos(radians(s.lat)) * cos(radians(c.lat)) * sin(radians(c.lon - s.lon) / 2) ^ 2)) as d
            from main.stations s, candidates c where s.lat is not null)
        select eva, arg_min(dwd_id, d), min(d) from pairs group by eva""")


def build():
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    LOCAL.unlink(missing_ok=True)
    splits = [s for s in schema.SPLITS if (DATA / f"{s}.tar").exists()]
    with duckdb.connect(str(LOCAL)) as con:
        print("stations and weather", flush=True)
        build_stations(con)
        build_weather(con)
        for split in splits:
            print(split, flush=True)
            build_timetables(con, split)
            build_questions(con, split)


def upload(only=()):
    with duckdb.connect(str(LOCAL), read_only=True) as local, db.connect() as remote:
        tables = local.execute("select schema_name, table_name from duckdb_tables() order by all").fetchall()
        for sch, tbl in tables:
            name = f"{sch}.{tbl}"
            if only and name not in only:
                continue
            cols = local.execute("select column_name, data_type from duckdb_columns() "
                                 "where schema_name = ? and table_name = ? order by column_index", [sch, tbl])
            remote.execute(f"create schema if not exists {sch}")
            remote.execute(f"create or replace table {name} ({', '.join(f'{c} {t}' for c, t in cols.fetchall())})")
            n_local = local.execute(f"select count(*) from {name}").fetchone()[0]
            # small batches, each its own COPY, so the server never holds much of a table in memory
            with tempfile.TemporaryDirectory(dir=LOCAL.parent) as d:
                csv = Path(d) / "batch.csv"
                for start in range(0, n_local, UPLOAD_BATCH_ROWS):
                    local.execute(f"copy (select * from {name} where rowid >= {start} "
                                  f"and rowid < {start + UPLOAD_BATCH_ROWS}) to '{csv}' (header false, nullstr '\\N')")
                    with remote.cursor().copy(f"copy {name} from stdin (format csv, null '\\N')") as cp:
                        cp.write(csv.read_bytes())
            n_remote = remote.execute(f"select count(*) from {name}").fetchone()[0]
            print(f"{name}: {n_remote:,} rows" + ("" if n_local == n_remote else f" (local has {n_local:,})"),
                  flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] != ["upload"]:
        build()
    upload(sys.argv[2:])
