"""SQLite 持久化与审计事件。

用标准库 sqlite3 保存通告、抽取、指引与审计事件，保证值班轮换后仍可
查回每条指引所依据的原文。所有写入在同一连接内提交，文件路径由调用方给定。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import (
    ActionType,
    Audience,
    Guidance,
    GuidanceStatus,
    Notice,
    SourceKind,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
    id TEXT PRIMARY KEY,
    language TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    received_at TEXT NOT NULL,
    translation_of TEXT
);
CREATE TABLE IF NOT EXISTS extractions (
    uid TEXT PRIMARY KEY,
    notice_id TEXT NOT NULL,
    clause_index INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guidances (
    gid TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    audience TEXT NOT NULL,
    subject_id TEXT,
    window TEXT,
    basis TEXT NOT NULL,
    route_detail TEXT,
    block_reasons TEXT,
    invalidated_reason TEXT,
    superseded_by TEXT,
    is_relay INTEGER NOT NULL,
    translation_derived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event TEXT NOT NULL
);
"""


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def save_notice(self, notice: Notice) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO notices VALUES (?, ?, ?, ?, ?, ?)",
            (
                notice.id, notice.language.value, notice.kind.value, notice.text,
                notice.received_at.isoformat(timespec="minutes"), notice.translation_of,
            ),
        )
        self.conn.commit()

    def save_extractions(self, notice_id: str, extractions) -> None:
        for ex in extractions:
            payload = {
                "force": ex.force.value,
                "action": ex.action.value,
                "span": ex.span,
                "negated": ex.negated,
                "audience": ex.audience.value,
                "place_id": ex.place_id,
                "mention": ex.mention,
                "generic_place": ex.generic_place,
                "window": ex.window.describe() if ex.window else None,
                "condition": ex.condition.describe() if ex.condition else None,
                "issues": ex.issues,
                "translation_blocked": ex.translation_blocked,
            }
            self.conn.execute(
                "INSERT OR REPLACE INTO extractions VALUES (?, ?, ?, ?)",
                (ex.uid, notice_id, ex.clause_index, json.dumps(payload, ensure_ascii=False)),
            )
        self.conn.commit()

    def save_guidance(self, guidance: Guidance) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO guidances VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guidance.gid, guidance.status.value, guidance.title, guidance.audience.value,
                guidance.subject_id,
                guidance.window.describe() if guidance.window else None,
                json.dumps([b.__dict__ for b in guidance.basis], ensure_ascii=False),
                guidance.route_detail,
                json.dumps(guidance.block_reasons, ensure_ascii=False),
                guidance.invalidated_reason,
                guidance.superseded_by,
                int(guidance.is_relay),
                int(guidance.translation_derived),
            ),
        )
        self.conn.commit()

    def log_event(self, event: str, moment: datetime | None = None) -> None:
        self.conn.execute(
            "INSERT INTO audit_events (created_at, event) VALUES (?, ?)",
            ((moment or datetime.now()).isoformat(timespec="minutes"), event),
        )
        self.conn.commit()

    def load_notice(self, notice_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM notices WHERE id = ?", (notice_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_guidances(self, status: GuidanceStatus | None = None) -> list[dict]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM guidances WHERE status = ? ORDER BY gid", (status.value,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM guidances ORDER BY gid").fetchall()
        return [dict(r) for r in rows]

    def audit_trail(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
        return [dict(r) for r in rows]
