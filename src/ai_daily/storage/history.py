from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


class HistoryStore:
    def __init__(self, path: Path, logger=None):
        self.path = path
        self.logger = logger
        self.records: list[dict] = []
        self.dirty = False
        self.load()

    def load(self) -> list[dict]:
        if not self.path.exists():
            self.records = []
            return self.records
        try:
            self.records = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.records, list):
                self.records = []
        except (OSError, json.JSONDecodeError):
            self.records = []
        self.prune()
        return self.records

    def prune(self, days: int = 30) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        kept = []
        for record in self.records:
            value = record.get("last_sent") or record.get("last_seen")
            try:
                date = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else datetime.min.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if date >= cutoff:
                kept.append(record)
        if len(kept) != len(self.records):
            self.dirty = True
        self.records = kept

    @staticmethod
    def content_hash(title: str, content: str) -> str:
        return hashlib.sha256(f"{title}\n{content}".encode("utf-8")).hexdigest()

    def find(self, item_id: str, canonical_url: str = "", cluster_id: str | None = None) -> dict | None:
        for record in self.records:
            if item_id and record.get("id") == item_id:
                return record
            if canonical_url and record.get("canonical_url") == canonical_url:
                return record
            if cluster_id and record.get("cluster_id") == cluster_id:
                return record
        return None

    def is_new_or_updated(self, *, item_id: str, canonical_url: str, cluster_id: str | None, title: str, content: str) -> tuple[bool, bool]:
        record = self.find(item_id, canonical_url, cluster_id)
        if not record:
            return True, False
        changed = record.get("content_hash") != self.content_hash(title, content)
        return changed, changed

    def mark_sent(self, *, item_id: str, canonical_url: str, cluster_id: str | None, title: str, content: str, update: bool = False) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        record = self.find(item_id, canonical_url, cluster_id)
        values = {"id": item_id, "canonical_url": canonical_url, "cluster_id": cluster_id, "title": title, "first_seen": record.get("first_seen", now) if record else now, "last_seen": now, "last_sent": now, "content_hash": self.content_hash(title, content), "update": update}
        if record:
            record.update(values)
        else:
            self.records.append(values)
        self.dirty = True
        return True

    def save(self) -> bool:
        if not self.dirty and self.path.exists():
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="seen_items_", suffix=".tmp", dir=self.path.parent)
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                json.dump(self.records, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            Path(temp_name).replace(self.path)
            self.dirty = False
            return True
        finally:
            temp = Path(temp_name)
            if temp.exists():
                temp.unlink()
