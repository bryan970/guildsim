from guild_runtime import runtime_root, usable_faction
"""Versioned local index of exact fight inputs and native comparison results."""
import json
from pathlib import Path
import sqlite3
from contextlib import closing


def register_profiles(root,profiles,engine_commit,enabled=()):
    path=Path(root)/'output/fight-library.sqlite';path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=30)) as db:
        if db.execute('PRAGMA user_version').fetchone()[0] not in (0,1):raise ValueError('Unsupported fight-library schema version')
        db.execute('''CREATE TABLE IF NOT EXISTS fight_profiles (
            profile_key TEXT NOT NULL, engine_commit TEXT NOT NULL, label TEXT NOT NULL,
            profile_json TEXT NOT NULL, enabled INTEGER NOT NULL,
            PRIMARY KEY(profile_key,engine_commit))''')
        for profile in profiles.values():
            db.execute('INSERT OR REPLACE INTO fight_profiles VALUES (?,?,?,?,?)',(
                profile['key'],engine_commit,profile['label'],json.dumps(profile,sort_keys=True),int(profile['key'] in enabled)))
        db.commit()


def record(root,payload,profile,request):
    path=Path(root)/'output/fight-library.sqlite';path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=30)) as db:
        version=db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0,1):raise ValueError('Unsupported fight-library schema version')
        if not version:db.execute('PRAGMA user_version=1')
        db.execute('''CREATE TABLE IF NOT EXISTS fight_runs (
            run_id TEXT PRIMARY KEY, analysis_kind TEXT NOT NULL, profile_key TEXT NOT NULL,
            profile_label TEXT NOT NULL, profile_json TEXT NOT NULL, character_guid TEXT NOT NULL,
            engine_commit TEXT NOT NULL, generated INTEGER NOT NULL, duration REAL NOT NULL,
            target_level INTEGER NOT NULL, baseline_dps REAL, request_json TEXT NOT NULL,
            complete INTEGER NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS fight_results (
            run_id TEXT NOT NULL, candidate_key TEXT NOT NULL, dps REAL NOT NULL,
            delta REAL NOT NULL, iterations INTEGER NOT NULL, provisional INTEGER NOT NULL,
            payload_json TEXT NOT NULL, PRIMARY KEY(run_id,candidate_key),
            FOREIGN KEY(run_id) REFERENCES fight_runs(run_id))''')
        db.execute('CREATE INDEX IF NOT EXISTS fight_lookup ON fight_runs(character_guid,profile_key,engine_commit,generated)')
        db.execute('INSERT OR REPLACE INTO fight_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(
            payload['runId'],'trinket_pairs',profile['key'],profile['label'],json.dumps(profile,sort_keys=True),
            payload['guid'],payload['engineCommit'],payload['generated'],payload['duration'],payload['targetLevel'],
            payload['baselineDps'],json.dumps(request,sort_keys=True),int(payload['complete'])))
        for row in payload['rows']:
            db.execute('INSERT OR REPLACE INTO fight_results VALUES (?,?,?,?,?,?,?)',(
                payload['runId'],row['key'],row['dps'],row['delta'],row['iterations'],int(row['provisional']),json.dumps(row,sort_keys=True)))
        db.commit()
