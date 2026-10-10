"""Append-only audit trail: output/audit_trail.json.

The file is a JSON array of AuditEvent records. Every run appends; nothing is
ever wiped. Each write goes to a temp file first and then replaces the old
file, so a crash mid-write can't corrupt the trail. If the existing file is
not valid JSON it is moved aside (never deleted) and a new array is started.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import AuditEvent

from .config import AUDIT_PATH

MAX_TEXT = 4000  # long free text is trimmed; structured tool data is kept whole


def _trim(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= MAX_TEXT else value[:MAX_TEXT] + f"... [+{len(value) - MAX_TEXT} chars]"
    if isinstance(value, dict):
        return {k: _trim(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_trim(v) for v in value]
    return value


class AuditTrail:
    def __init__(self, path: Path = AUDIT_PATH) -> None:
        self.path = path
        self.run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]
        self.shop_date: str | None = None
        self.seq = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._events = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
        backup = self.path.with_suffix(f".corrupt-{datetime.now():%Y%m%d%H%M%S}.json")
        self.path.rename(backup)
        return []

    def log(
        self,
        event: str,
        *,
        ticket_id: int | None = None,
        agent: str | None = None,
        depth: int | None = None,
        **data: Any,
    ) -> dict[str, Any]:
        rec = AuditEvent(
            ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            run_id=self.run_id,
            seq=self.seq,
            event=event,
            shop_date=self.shop_date,
            ticket_id=ticket_id,
            agent=agent,
            depth=depth,
            data=_trim(json.loads(json.dumps(data, default=str))),
        ).model_dump()
        self.seq += 1
        self._events.append(rec)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._events, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
        return rec
