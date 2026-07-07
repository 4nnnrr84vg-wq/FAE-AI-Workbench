from __future__ import annotations

import datetime as dt
import threading
import time


class SimpleScheduler:
    def __init__(self, config: dict, send_job_callback):
        self.enabled = bool(config.get("scheduler", {}).get("enabled", False))
        self.jobs = config.get("scheduler", {}).get("jobs", [])
        self._callback = send_job_callback
        self._running = False
        self._thread = None
        self._last_run = {}

    def start(self):
        if not self.enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            now = dt.datetime.now()
            current_hm = now.strftime("%H:%M")
            current_day = now.strftime("%Y-%m-%d")
            for i, job in enumerate(self.jobs):
                if job.get("at") != current_hm:
                    continue
                key = f"{i}:{current_day}"
                if self._last_run.get(key):
                    continue
                self._callback(job)
                self._last_run[key] = True
            time.sleep(20)
