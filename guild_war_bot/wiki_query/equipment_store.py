from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator


SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS characters (
    character_id TEXT PRIMARY KEY,
    character_name TEXT NOT NULL UNIQUE,
    wiki_name TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS equipment_affixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    character_id TEXT NOT NULL REFERENCES characters(character_id),
    slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 5),
    affix_type TEXT NOT NULL,
    affix_value REAL NOT NULL,
    value_text TEXT NOT NULL DEFAULT '',
    tier INTEGER NOT NULL CHECK(tier BETWEEN 0 AND 15),
    source_ocr_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, character_id, slot, affix_type)
);
CREATE TABLE IF NOT EXISTS ocr_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    image_sha256 TEXT NOT NULL,
    image_path TEXT NOT NULL,
    raw_text TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'success',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, image_sha256)
);
CREATE TABLE IF NOT EXISTS import_sessions (
    user_id TEXT PRIMARY KEY,
    step TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class EquipmentStore:
    """词条功能的独立 SQLite 存储，不复用会战数据库。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            self._migrate_tier_constraint(db)

    @staticmethod
    def _migrate_tier_constraint(db: sqlite3.Connection) -> None:
        row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='equipment_affixes'"
        ).fetchone()
        table_sql = str(row["sql"] or "") if row else ""
        compact = "".join(table_sql.split()).lower()
        if "tierbetween0and3" not in compact:
            return
        db.executescript(
            """
            ALTER TABLE equipment_affixes RENAME TO equipment_affixes_legacy;
            CREATE TABLE equipment_affixes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL REFERENCES users(user_id),
                character_id TEXT NOT NULL REFERENCES characters(character_id),
                slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 5),
                affix_type TEXT NOT NULL,
                affix_value REAL NOT NULL,
                value_text TEXT NOT NULL DEFAULT '',
                tier INTEGER NOT NULL CHECK(tier BETWEEN 0 AND 15),
                source_ocr_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, character_id, slot, affix_type)
            );
            INSERT INTO equipment_affixes
            SELECT * FROM equipment_affixes_legacy;
            DROP TABLE equipment_affixes_legacy;
            """
        )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def ensure_user(self, user_id: str, display_name: str = "") -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO users(user_id, display_name) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET display_name=excluded.display_name,
                updated_at=CURRENT_TIMESTAMP""",
                (str(user_id), display_name),
            )

    def ensure_character(self, character_id: str, name: str, wiki_name: str = "") -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO characters(character_id, character_name, wiki_name)
                VALUES (?, ?, ?)
                ON CONFLICT(character_id) DO UPDATE SET character_name=excluded.character_name,
                wiki_name=excluded.wiki_name""",
                (character_id, name, wiki_name),
            )

    def save_ocr(
        self,
        user_id: str,
        image_path: Path,
        result: dict[str, Any],
    ) -> int:
        image_hash = sha256_file(image_path)
        rows = result.get("rows") or []
        confidence = float(result.get("confidence") or 0)
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO ocr_history
                (user_id, image_sha256, image_path, raw_text, result_json, confidence, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, image_sha256) DO UPDATE SET
                image_path=excluded.image_path, raw_text=excluded.raw_text,
                result_json=excluded.result_json, confidence=excluded.confidence,
                status=excluded.status, error_message='', created_at=CURRENT_TIMESTAMP""",
                (
                    str(user_id), image_hash, str(image_path), str(result.get("raw_text") or ""),
                    json.dumps(rows, ensure_ascii=False), confidence, str(result.get("status") or "success"),
                ),
            )
            row = db.execute(
                "SELECT id FROM ocr_history WHERE user_id=? AND image_sha256=?",
                (str(user_id), image_hash),
            ).fetchone()
            return int(row["id"] if row else cursor.lastrowid)

    def save_session(self, user_id: str, step: str, payload: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO import_sessions(user_id, step, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET step=excluded.step,
                payload_json=excluded.payload_json, updated_at=CURRENT_TIMESTAMP""",
                (str(user_id), step, json.dumps(payload, ensure_ascii=False)),
            )

    def load_session(self, user_id: str) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM import_sessions WHERE user_id=?", (str(user_id),)
            ).fetchone()

    def delete_session(self, user_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM import_sessions WHERE user_id=?", (str(user_id),))

    def commit_affixes(
        self,
        user_id: str,
        character_id: str,
        character_name: str,
        rows: Iterable[dict[str, Any]],
    ) -> int:
        rows = list(rows)
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO users(user_id) VALUES (?)", (str(user_id),)
            )
            db.execute(
                """INSERT INTO characters(character_id, character_name) VALUES (?, ?)
                ON CONFLICT(character_id) DO UPDATE SET character_name=excluded.character_name""",
                (character_id, character_name),
            )
            for row in rows:
                slot = int(row["slot"])
                tier = int(row.get("tier") or 0)
                if slot not in range(1, 6):
                    raise ValueError(f"装备槽位超出范围: {slot}")
                if tier not in range(0, 16):
                    raise ValueError(f"词条阶数超出范围: {tier}")
                db.execute(
                    """INSERT INTO equipment_affixes
                    (user_id, character_id, slot, affix_type, affix_value, value_text, tier, source_ocr_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, character_id, slot, affix_type) DO UPDATE SET
                    affix_value=excluded.affix_value, value_text=excluded.value_text,
                    tier=excluded.tier, source_ocr_id=excluded.source_ocr_id,
                    updated_at=CURRENT_TIMESTAMP""",
                    (
                        str(user_id), character_id, slot, str(row["affix_type"]),
                        float(row["affix_value"]), str(row.get("value_text") or ""),
                        tier, row.get("source_ocr_id"),
                    ),
                )
        return len(rows)

    def list_affixes(self, user_id: str, character_id: str | None = None) -> list[dict[str, Any]]:
        sql = """SELECT e.*, c.character_name FROM equipment_affixes e
                 JOIN characters c ON c.character_id=e.character_id
                 WHERE e.user_id=?"""
        params: list[Any] = [str(user_id)]
        if character_id:
            sql += " AND e.character_id=?"
            params.append(character_id)
        sql += " ORDER BY e.character_id, e.slot, e.tier DESC, e.affix_value DESC"
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def cached_ocr(self, user_id: str, image_path: Path) -> dict[str, Any] | None:
        image_hash = sha256_file(image_path)
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM ocr_history WHERE user_id=? AND image_sha256=?",
                (str(user_id), image_hash),
            ).fetchone()
        if not row or row["status"] not in {"success", "needs_review"}:
            return None
        return {
            "ocr_id": int(row["id"]),
            "rows": json.loads(row["result_json"]),
            "confidence": row["confidence"],
            "raw_text": row["raw_text"],
            "status": row["status"],
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
