"""Parse the raw timetable snapshots into rows of src/schema.py tables.

Snapshots are read straight from data/<split>.tar, nothing is unpacked to disk.
Times are kept as the raw strings here ('YYMMDDHHmm', snapshot 'YYYYmmdd_HHMMSS');
they are converted to timestamps when loaded into the database.
"""
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def snapshots(split, kind):
    """(member name, snapshot 'YYYYmmdd_HHMMSS') of every plan/fchg snapshot in data/<split>.tar."""
    with tarfile.open(DATA / f"{split}.tar") as t:
        names = [m.name for m in t if m.name.startswith(f"{split}/{kind}/") and m.name.endswith(".tar.gz")]
    return sorted((n, Path(n).name[:15]) for n in names)


def _station_files(split, member):
    """Yield (eva, root element) for each station XML in one snapshot."""
    with tarfile.open(DATA / f"{split}.tar") as outer:
        with tarfile.open(fileobj=outer.extractfile(member), mode="r:gz") as inner:
            for m in inner:
                if m.isfile() and m.name.endswith(".xml"):
                    yield Path(m.name).stem, ET.fromstring(inner.extractfile(m).read())


def parse_plan(split, member, snapshot):
    rows = []
    for eva, root in _station_files(split, member):
        station = root.get("station")
        for s in root.iter("s"):
            s_id = s.get("id")
            trip_id, stop_idx = s_id.rsplit("-", 1)
            tl = s.find("tl")
            tl = tl.attrib if tl is not None else {}
            ar = s.find("ar")
            dp = s.find("dp")
            ar = ar.attrib if ar is not None else {}
            dp = dp.attrib if dp is not None else {}
            rows.append((snapshot, s_id, trip_id, stop_idx, eva, station, tl.get("c"), tl.get("n"),
                         tl.get("f"), ar.get("l") or dp.get("l"), ar.get("pt"), dp.get("pt"),
                         ar.get("pp") or dp.get("pp"), ar.get("ppth"), dp.get("ppth")))
    return rows


def _messages(rows, snapshot, s_id, eva, event, parent):
    for m in parent.findall("m"):
        a = m.attrib
        rows.append((snapshot, s_id, eva, event, a.get("id"), a.get("t"), a.get("c"), a.get("cat"),
                     a.get("ts"), a.get("from"), a.get("to")))


def parse_fchg(split, member, snapshot):
    changes, messages = [], []
    for eva, root in _station_files(split, member):
        _messages(messages, snapshot, None, eva, "station", root)
        for s in root.iter("s"):
            s_id = s.get("id")
            _messages(messages, snapshot, s_id, eva, "stop", s)
            ar = s.find("ar")
            dp = s.find("dp")
            for event, e in (("ar", ar), ("dp", dp)):
                if e is not None:
                    _messages(messages, snapshot, s_id, eva, event, e)
            ar = ar.attrib if ar is not None else {}
            dp = dp.attrib if dp is not None else {}
            changes.append((snapshot, s_id, eva, ar.get("ct"), dp.get("ct"), ar.get("cs"), dp.get("cs"),
                            ar.get("clt"), dp.get("clt"), ar.get("cp") or dp.get("cp")))
    return changes, messages
