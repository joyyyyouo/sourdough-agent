import sqlite3


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scrape_runs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            scraped_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS forecasts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            scrape_run_id INTEGER NOT NULL REFERENCES scrape_runs(id),
            forecast_time TEXT NOT NULL,
            temperature_c REAL NOT NULL,
            humidity_pct  REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_forecasts_scrape_run ON forecasts(scrape_run_id);
        CREATE INDEX IF NOT EXISTS idx_forecasts_time ON forecasts(forecast_time);

        CREATE TABLE IF NOT EXISTS bake_sessions (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at           TEXT NOT NULL,
            starter_health       TEXT NOT NULL,
            deadline             TEXT NOT NULL,
            last_fed_at          TEXT NOT NULL,
            feeding_ratio        TEXT NOT NULL,
            earliest_start_time  TEXT,
            scrape_run_id        INTEGER REFERENCES scrape_runs(id),
            weather_hour0_temp_c REAL,
            weather_hour2_temp_c REAL,
            weather_hour5_temp_c REAL
        );

        CREATE TABLE IF NOT EXISTS bake_schedules (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            bake_session_id  INTEGER NOT NULL REFERENCES bake_sessions(id),
            step_time        TEXT NOT NULL,
            step_label       TEXT NOT NULL,
            duration_minutes INTEGER,
            notes            TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_bake_schedules_session
            ON bake_schedules(bake_session_id);

        CREATE TABLE IF NOT EXISTS user_availability (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            bake_session_id  INTEGER NOT NULL REFERENCES bake_sessions(id),
            unavailable_from TEXT NOT NULL,
            unavailable_to   TEXT NOT NULL,
            reason           TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_user_availability_session
            ON user_availability(bake_session_id);

        CREATE TABLE IF NOT EXISTS user_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_key     TEXT NOT NULL UNIQUE,
            thread_id       TEXT NOT NULL UNIQUE,
            bake_session_id INTEGER REFERENCES bake_sessions(id),
            bot_name        TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            last_seen_at    TEXT NOT NULL,
            bake_phase      TEXT NOT NULL DEFAULT 'planning'
                                CHECK(bake_phase IN ('planning','monitoring','complete'))
        );

        CREATE INDEX IF NOT EXISTS idx_user_sessions_key
            ON user_sessions(session_key);

        CREATE TABLE IF NOT EXISTS agent_checkpoints (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id   TEXT NOT NULL UNIQUE,
            state_json  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
    """)

    # Migrations: add columns to bake_sessions if not present
    for ddl in [
        "ALTER TABLE bake_sessions ADD COLUMN thread_id TEXT",
        "ALTER TABLE bake_sessions ADD COLUMN earliest_start_time TEXT",
        "ALTER TABLE bake_sessions ADD COLUMN scrape_run_id INTEGER",
        "ALTER TABLE bake_sessions ADD COLUMN weather_hour0_temp_c REAL",
        "ALTER TABLE bake_sessions ADD COLUMN weather_hour2_temp_c REAL",
        "ALTER TABLE bake_sessions ADD COLUMN weather_hour5_temp_c REAL",
    ]:
        try:
            conn.execute(ddl)
            conn.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise

    conn.commit()
    return conn


def insert_scrape_run(conn: sqlite3.Connection, scraped_at: str) -> int:
    cur = conn.execute("INSERT INTO scrape_runs (scraped_at) VALUES (?)", (scraped_at,))
    conn.commit()
    return cur.lastrowid


def insert_forecasts(conn: sqlite3.Connection, scrape_run_id: int, rows: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO forecasts (scrape_run_id, forecast_time, temperature_c, humidity_pct) VALUES (?, ?, ?, ?)",  # noqa: E501
        [(scrape_run_id, r["forecast_time"], r["temperature_c"], r["humidity_pct"]) for r in rows],
    )
    conn.commit()


def insert_bake_session(
    conn: sqlite3.Connection,
    created_at: str,
    starter_health: str,
    deadline: str,
    last_fed_at: str,
    feeding_ratio: str,
    earliest_start_time: str | None = None,
    thread_id: str | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO bake_sessions
           (created_at, starter_health, deadline, last_fed_at, feeding_ratio,
            earliest_start_time, thread_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            created_at,
            starter_health,
            deadline,
            last_fed_at,
            feeding_ratio,
            earliest_start_time,
            thread_id,
        ),
    )
    conn.commit()
    return cur.lastrowid


def insert_bake_schedule_steps(
    conn: sqlite3.Connection,
    bake_session_id: int,
    steps: list[dict],
) -> None:
    conn.executemany(
        """INSERT INTO bake_schedules
           (bake_session_id, step_time, step_label, duration_minutes, notes)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (
                bake_session_id,
                s["step_time"],
                s["step_label"],
                s.get("duration_minutes"),
                s.get("notes"),
            )
            for s in steps
        ],
    )
    conn.commit()


def insert_user_availability(
    conn: sqlite3.Connection,
    bake_session_id: int,
    conflicts: list[dict],
) -> None:
    conn.executemany(
        """INSERT INTO user_availability
           (bake_session_id, unavailable_from, unavailable_to, reason)
           VALUES (?, ?, ?, ?)""",
        [
            (
                bake_session_id,
                c["unavailable_from"],
                c["unavailable_to"],
                c.get("reason"),
            )
            for c in conflicts
        ],
    )
    conn.commit()


def upsert_user_session(
    conn: sqlite3.Connection,
    session_key: str,
    thread_id: str,
    bot_name: str,
    created_at: str,
    last_seen_at: str,
) -> None:
    conn.execute(
        """INSERT INTO user_sessions (session_key, thread_id, bot_name, created_at, last_seen_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(session_key) DO UPDATE SET last_seen_at = excluded.last_seen_at""",
        (session_key, thread_id, bot_name, created_at, last_seen_at),
    )
    conn.commit()


def get_user_session(conn: sqlite3.Connection, session_key: str) -> dict | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM user_sessions WHERE session_key = ?", (session_key,)
    ).fetchone()
    return dict(row) if row else None


def save_checkpoint(conn: sqlite3.Connection, thread_id: str, state_json: str) -> None:
    """Upsert the agent state JSON for a thread."""
    now = (
        __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    conn.execute(
        """INSERT INTO agent_checkpoints (thread_id, state_json, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(thread_id) DO UPDATE SET state_json = excluded.state_json,
                                                updated_at = excluded.updated_at""",
        (thread_id, state_json, now),
    )
    conn.commit()


def load_checkpoint(conn: sqlite3.Connection, thread_id: str) -> str | None:
    """Return the state JSON for a thread, or None if not found."""
    row = conn.execute(
        "SELECT state_json FROM agent_checkpoints WHERE thread_id = ?", (thread_id,)
    ).fetchone()
    return row[0] if row else None


def get_latest_scrape_run(conn: sqlite3.Connection) -> dict | None:
    """Return {id, scraped_at} of the most recent scrape_run, or None."""
    row = conn.execute("SELECT id, scraped_at FROM scrape_runs ORDER BY id DESC LIMIT 1").fetchone()
    return {"id": row[0], "scraped_at": row[1]} if row else None


def get_forecasts_for_run(conn: sqlite3.Connection, scrape_run_id: int) -> list[dict]:
    """Return all forecast rows for a scrape_run, ordered by forecast_time."""
    rows = conn.execute(
        "SELECT forecast_time, temperature_c, humidity_pct FROM forecasts "
        "WHERE scrape_run_id = ? ORDER BY forecast_time",
        (scrape_run_id,),
    ).fetchall()
    return [{"forecast_time": r[0], "temperature_c": r[1], "humidity_pct": r[2]} for r in rows]


def update_bake_session_weather(
    conn: sqlite3.Connection,
    bake_session_id: int,
    scrape_run_id: int,
    hour0: float | None,
    hour2: float | None,
    hour5: float | None,
) -> None:
    """Persist the scrape run and computed weighted temps onto the bake_session row."""
    conn.execute(
        """UPDATE bake_sessions
           SET scrape_run_id = ?, weather_hour0_temp_c = ?,
               weather_hour2_temp_c = ?, weather_hour5_temp_c = ?
           WHERE id = ?""",
        (scrape_run_id, hour0, hour2, hour5, bake_session_id),
    )
    conn.commit()


def update_session_bake_data(
    conn: sqlite3.Connection,
    session_key: str,
    bake_session_id: int,
    bake_phase: str,
) -> None:
    conn.execute(
        """UPDATE user_sessions
           SET bake_session_id = ?, bake_phase = ?
           WHERE session_key = ?""",
        (bake_session_id, bake_phase, session_key),
    )
    conn.commit()
