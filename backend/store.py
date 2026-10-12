import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


def now():
    return int(time.time() * 1000)


class Store:
    def __init__(self, data: Path):
        self.data = data
        for name in ('snapshots', 'thumbnails'):
            (data / name).mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS people (
                    id TEXT PRIMARY KEY, directory TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                    locked_id TEXT, baseline_id TEXT, baseline_hash TEXT, mode TEXT NOT NULL DEFAULT 'missing',
                    version INTEGER NOT NULL DEFAULT 0, last_scan INTEGER NOT NULL DEFAULT 0, rules TEXT);
                CREATE TABLE IF NOT EXISTS photos (
                    id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(id),
                    path TEXT UNIQUE NOT NULL, original_name TEXT NOT NULL, device INTEGER, inode INTEGER,
                    size INTEGER, mtime INTEGER, hash TEXT, status TEXT NOT NULL,
                    score REAL, metrics TEXT, engine TEXT, error TEXT,
                    added INTEGER NOT NULL, present INTEGER NOT NULL DEFAULT 1,
                    rank INTEGER, metadata TEXT, writeback TEXT NOT NULL DEFAULT 'none', named_baseline INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS photos_person ON photos(person_id);
                CREATE TABLE IF NOT EXISTS scores (
                    hash TEXT NOT NULL, engine TEXT NOT NULL, result TEXT NOT NULL,
                    PRIMARY KEY(hash, engine));
                CREATE TABLE IF NOT EXISTS history (
                    person_id TEXT NOT NULL, version INTEGER NOT NULL, at INTEGER NOT NULL,
                    reason TEXT NOT NULL, mode TEXT NOT NULL, photo_id TEXT, hash TEXT,
                    file_name TEXT, score REAL, snapshot TEXT,
                    PRIMARY KEY(person_id, version));
                CREATE TABLE IF NOT EXISTS operations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, person_id TEXT NOT NULL, photo_id TEXT,
                    kind TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', error TEXT, created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            if not db.execute('SELECT 1 FROM settings').fetchone():
                db.execute('INSERT INTO settings VALUES(1,?)', (json.dumps({
                    'folders': [], 'k': 5, 'model': 'faceqnet', 'threshold': 40,
                    'thresholds': {'faceqnet': 40, 'ofiq': 60}
                }, ensure_ascii=False),))
            settings = json.loads(db.execute('SELECT value FROM settings WHERE id=1').fetchone()[0])
            if 'root' in settings:
                root = Path(settings.pop('root'))
                settings['folders'] = [r['directory'] for r in db.execute('SELECT directory FROM people ORDER BY name,id')
                                       if Path(r['directory']).parent == root]
                db.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(settings, ensure_ascii=False),))
            if 'model' not in settings:
                settings.update(model='faceqnet', thresholds={'ofiq': settings['threshold'], 'faceqnet': 40}, threshold=40)
                db.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(settings, ensure_ascii=False),))
            if 'engine' not in [r['name'] for r in db.execute('PRAGMA table_info(history)')]:
                db.execute('ALTER TABLE history ADD COLUMN engine TEXT')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.data / 'baseline.sqlite', timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def settings(self):
        with self.connect() as db:
            return json.loads(db.execute('SELECT value FROM settings WHERE id=1').fetchone()[0])

    def job(self, job):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?)', (job['id'], json.dumps(job, ensure_ascii=False)))

    def jobs(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT value FROM jobs ORDER BY rowid DESC LIMIT 50')]
