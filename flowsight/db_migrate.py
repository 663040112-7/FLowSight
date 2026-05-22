# =============================================================================
# db_migrate.py — Migrate old behavior_log.db to new format
# Run once if you have old DB from wine_web
# =============================================================================
import sqlite3, os

DB = "behavior_log.db"

if not os.path.exists(DB):
    print(f"No {DB} found — nothing to migrate")
    exit(0)

conn = sqlite3.connect(DB)
migrations = [
    ("zone_name",     "ALTER TABLE events ADD COLUMN zone_name TEXT DEFAULT ''"),
    ("behavior_id",   "ALTER TABLE events ADD COLUMN behavior_id TEXT DEFAULT ''"),
    ("behavior_name", "ALTER TABLE events ADD COLUMN behavior_name TEXT DEFAULT ''"),
    ("is_new_visit",  "ALTER TABLE events ADD COLUMN is_new_visit INTEGER DEFAULT 1"),
]

for col, sql in migrations:
    try:
        conn.execute(sql)
        print(f"✅ Added column: {col}")
    except Exception:
        print(f"   Skip (exists): {col}")

# backfill from old 'behavior' column
try:
    conn.execute("""UPDATE events SET 
        behavior_id=behavior, behavior_name=behavior 
        WHERE behavior_id='' AND behavior IS NOT NULL""")
    conn.execute("""UPDATE events SET is_new_visit=1 WHERE is_new_visit IS NULL""")
    print("✅ Backfilled data from old columns")
except Exception as e:
    print(f"   Backfill: {e}")

conn.commit()
rows = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
print(f"\n✅ Migration complete — {rows:,} events in DB")
conn.close()
