# logger.py — FlowSight BehaviorLogger  v1.1
import sqlite3, time, logging
from behavior_engine import PersonState

log = logging.getLogger("flowsight.logger")

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     REAL    NOT NULL,
    cam_key       TEXT    NOT NULL DEFAULT 'cam_0',
    person_id     INTEGER NOT NULL,
    zone          TEXT    NOT NULL DEFAULT 'floor',
    zone_name     TEXT    NOT NULL DEFAULT '',
    behavior_id   TEXT    NOT NULL DEFAULT '',
    behavior_name TEXT    NOT NULL DEFAULT '',
    needs_staff   INTEGER NOT NULL DEFAULT 0,
    is_new_visit  INTEGER NOT NULL DEFAULT 1
)
"""
INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_ts ON events(timestamp)"

class BehaviorLogger:
    FLUSH_EVERY       = 30
    PERSON_COOLDOWN_SEC = 120

    def __init__(self, db_path: str = "behavior_log.db"):
        self._db_path = db_path
        self.conn     = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(CREATE_SQL)
        self.conn.execute(INDEX_SQL)
        self.conn.commit()
        self._buf:  list = []
        self._seen: dict[str, float] = {}
        log.info("[Logger] DB ready: %s", db_path)

    def log(self, state: PersonState, cam_key: str = "cam_0",
            zone_name: str = "", video_ts: float | None = None):
        ts  = video_ts if video_ts is not None else time.time()
        key = f"{cam_key}_{state.person_id}"
        is_new = int(ts - self._seen.get(key, 0) > self.PERSON_COOLDOWN_SEC)
        self._seen[key] = ts
        self._buf.append((
            ts, cam_key, state.person_id,
            state.zone, zone_name or state.zone,
            state.behavior_id, state.behavior_name,
            int(state.needs_staff), is_new,
        ))
        if len(self._buf) >= self.FLUSH_EVERY:
            self._flush()

    def _flush(self):
        if not self._buf:
            return
        try:
            self.conn.executemany(
                "INSERT INTO events "
                "(timestamp,cam_key,person_id,zone,zone_name,"
                "behavior_id,behavior_name,needs_staff,is_new_visit) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                self._buf)
            self.conn.commit()
            self._buf.clear()
        except Exception as e:
            log.error("DB flush error: %s", e)

    def close(self):
        self._flush()
        try:
            self.conn.close()
        except Exception:
            pass
