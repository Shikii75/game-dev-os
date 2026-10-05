"""In-memory activity log + active pipeline jobs."""

from __future__ import annotations

import threading
import time
import uuid


class ActivityHub:
    def __init__(self, max_recent: int = 80):
        self._lock = threading.Lock()
        self._recent: list[dict] = []
        self._active: dict[str, dict] = {}
        self.max_recent = max_recent

    def log(self, action: str, detail: str | None = None, meta: dict | None = None):
        entry = {"t": time.time(), "action": action, "detail": detail or "", "meta": meta or {}}
        with self._lock:
            self._recent.append(entry)
            self._recent = self._recent[-self.max_recent :]

    def recent(self) -> list[dict]:
        with self._lock:
            return list(reversed(self._recent[-40:]))

    def job_start(self, label: str) -> str:
        jid = uuid.uuid4().hex[:12]
        with self._lock:
            self._active[jid] = {"label": label, "started": time.time(), "status": "running"}
        self.log("job_start", label, {"job_id": jid})
        return jid

    def job_done(self, jid: str):
        with self._lock:
            if jid in self._active:
                self._active.pop(jid, None)

    def job_fail(self, jid: str, err: str):
        with self._lock:
            if jid in self._active:
                self._active[jid]["status"] = "error"
                self._active[jid]["error"] = err
                self._active.pop(jid, None)
        self.log("job_error", err)

    def active_jobs(self) -> list[dict]:
        with self._lock:
            return [{"id": k, **v} for k, v in self._active.items()]


hub = ActivityHub()
