"""Shared table formats. All tables live in the team database (see src/db.py):
<split>.planned_stops, <split>.changes, <split>.messages and <split>.questions for each split,
and main.stations, main.weather, main.station_weather shared by all splits.

Conventions:
- times are datetimes in German local time, like the raw data (weather is converted from UTC on load)
- ids are strings (trip ids can be negative 19-digit numbers)
- s_id = "<daily trip id>-<YYMMDDHHmm trip start>-<stop index>"; the schema file says 6 digits
  for the date part, but the data has 10
- planned_stops, changes and messages hold a row only when the stop (or message) was not in the
  previous snapshot with the same values. snapshot_time is when that version was first seen, so the
  state at time `now` is the latest row with snapshot_time <= now.
"""
SPLITS = ("training", "val", "test")


# From plan/: one row per new or changed stop per plan snapshot
PLANNED_STOPS = {
    "snapshot_time": "datetime64[ns]",  # from the file name
    "s_id": "string",                   # <s id>
    "trip_id": "string",                # first two parts of s_id
    "stop_idx": "Int64",                # last part of s_id
    "eva": "string",                    # <timetable eva>; map stations by eva, not name
    "station": "string",                # <timetable station>
    "category": "string",               # <tl c>, e.g. ICE, RE, S
    "train_number": "string",           # <tl n>
    "filter_flag": "string",            # <tl f>, e.g. F, N, S; likely decides train_group
    "line": "string",                   # ar/dp l
    "planned_ar": "datetime64[ns]",     # ar pt
    "planned_dp": "datetime64[ns]",     # dp pt
    "platform": "string",               # pp
    "path_before": "string",            # ar ppth, stations before this one, '|'-separated
    "path_after": "string",             # dp ppth, stations after this one
}

# From fchg/: one row per new or changed stop per change snapshot.
# fchg sometimes also carries pt/ppth; those belong in PLANNED_STOPS-style columns, not here.
CHANGES = {
    "snapshot_time": "datetime64[ns]",
    "s_id": "string",
    "eva": "string",
    "changed_ar": "datetime64[ns]",     # ar ct: current estimate or actual time
    "changed_dp": "datetime64[ns]",     # dp ct
    "ar_status": "string",              # ar cs: p planned, a added, c cancelled
    "dp_status": "string",              # dp cs
    "ar_cancel_time": "datetime64[ns]", # ar clt
    "dp_cancel_time": "datetime64[ns]", # dp clt
    "changed_platform": "string",       # cp
}

# From fchg/: one row per new message per snapshot. The same msg_id can still appear on several
# stops and on both ar and dp.
MESSAGES = {
    "snapshot_time": "datetime64[ns]",
    "s_id": "string",                   # empty for station-wide messages
    "eva": "string",
    "event": "string",                  # ar, dp, stop or station
    "msg_id": "string",                 # m id
    "msg_type": "string",               # m t (see messageType in timetables_schema.json)
    "code": "Int64",                    # m c
    "category": "string",               # m cat
    "msg_time": "datetime64[ns]",       # m ts
    "valid_from": "datetime64[ns]",     # m from
    "valid_to": "datetime64[ns]",       # m to
}

# From stations.json: one row per EVA number (a few stations have several)
STATIONS = {
    "eva": "string",
    "name": "string",
    "lat": "float64",
    "lon": "float64",
    "category": "Int64",                # DB station category, 1 (largest) to 7
    "federal_state": "string",
    "is_main": "boolean",               # main EVA number of the station
}

# DWD 10-minute observations: one row per weather station and slot
WEATHER = {
    "dwd_id": "string",
    "time": "datetime64[ns]",           # local time (DWD is UTC)
    "temperature_c": "float64",
    "precip_mm": "float64",
    "wind_ms": "float64",
}

# Nearest weather station per DB station, among those reporting temperature, precipitation and wind
STATION_WEATHER = {
    "eva": "string",
    "dwd_id": "string",
    "distance_km": "float64",
}

# Questions and labels, same columns as val_questions.csv + scoring/val_answers.csv.
# Training has no questions; we generate them. Labels are empty for test.
QUESTIONS = {
    "question_id": "string",
    "now": "datetime64[ns]",
    "last_stop_s_id": "string",         # empty if the train has not reached a stop in the data yet
    "horizon": "Int64",                 # 10, 30 or 60
    "target_s_id": "string",
    "target_station": "string",
    "train_group": "string",            # S, regional or long
    "planned": "datetime64[ns]",        # planned arrival at the target stop
    "actual": "datetime64[ns]",         # actual arrival
    "delay_min": "float64",             # actual - planned, in minutes; early is negative
}
