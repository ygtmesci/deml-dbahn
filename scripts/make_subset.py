"""Extract a small, identical subset of the raw data for everyone.

Usage (from the repo root, with the course files in data/):
    python scripts/make_subset.py                    # default days
    python scripts/make_subset.py --days 20261029    # other days

Output:
    data/subset/<split>/<plan|fchg>/<YYYYMMDD_HHMMSS>.tar.gz   (inside: <YYYYMMDD_HHMMSS>/<EVA>.xml)
    data/subset/weather/...            (all weather, it is small)
    data/subset/val_questions.csv      (only questions on the chosen val days)
"""
import argparse
import csv
import shutil
import tarfile
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "subset"
DEFAULT_DAYS = ["20261029", "20261104"]  # one training day, one val day (cut-offs 08:00 and 18:00)


def extract_snapshots(archive, days):
    """Copy every plan/fchg snapshot of the given days, still compressed.

    Snapshots stay as .tar.gz (one XML per station inside): unpacked, two days are
    ~330k small files, and the parser has to read .tar.gz for the full data anyway.
    """
    count = 0
    with tarfile.open(archive) as outer:
        for member in outer:
            name = Path(member.name)  # e.g. training/plan/20261029_080001.tar.gz
            if not member.isfile() or not name.name.endswith(".tar.gz") or name.name[:8] not in days:
                continue
            dest = OUT / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with outer.extractfile(member) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    print(f"{archive.name}: {count} snapshots")


def subset_questions(days):
    yymmdd = {d[2:] for d in days}  # questions use YYMMDDHHMM
    with open(DATA / "val_questions.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    kept = [r for r in rows if r["now"][:6] in yymmdd]
    with open(OUT / "val_questions.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(kept)
    print(f"val_questions.csv: {len(kept)} of {len(rows)} questions")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", nargs="+", default=DEFAULT_DAYS, help="YYYYMMDD, training or val days")
    days = set(p.parse_args().days)

    if OUT.exists():
        shutil.rmtree(OUT)  # always rebuild, so everyone ends up with the same files
    OUT.mkdir(parents=True)

    for archive in ["training.tar", "val.tar"]:
        extract_snapshots(DATA / archive, days)
    with tarfile.open(DATA / "weather.tar") as t:
        t.extractall(OUT / "weather", filter="data")
    print("weather.tar: extracted")
    for f in ["stations.json", "timetables_schema.json"]:
        shutil.copy(DATA / f, OUT / f)
    subset_questions(days)


if __name__ == "__main__":
    main()
