"""Background scheduler thread.

Always running so the dashboard's "Run now" works, but it only performs an
*automatic* run when ENABLE_SCHEDULER is on (read live from settings each cycle).
"""
import logging
import threading
import time

log = logging.getLogger("recommendarr.scheduler")


class Scheduler(threading.Thread):
    def __init__(self, ctx):
        super().__init__(daemon=True)
        self.ctx = ctx
        self._trigger = threading.Event()
        self._stop = threading.Event()
        self.running = False
        self.last_run_ts = None
        self.last_summary = None
        self._next_due = time.time() + max(ctx.settings.RUN_INTERVAL_SECONDS, 60)

    def run_now(self):
        """Request an immediate run (used by the UI button)."""
        self._trigger.set()

    def stop(self):
        self._stop.set()
        self._trigger.set()

    def status(self) -> dict:
        return {
            "running": self.running,
            "last_run_ts": self.last_run_ts,
            "last_summary": self.last_summary,
            "enabled": bool(self.ctx.settings.ENABLE_SCHEDULER),
            "interval": int(self.ctx.settings.RUN_INTERVAL_SECONDS),
        }

    def run(self):
        while not self._stop.is_set():
            manual = self._trigger.wait(timeout=30)
            self._trigger.clear()
            if self._stop.is_set():
                break

            s = self.ctx.settings
            now = time.time()
            auto_due = (
                bool(s.ENABLE_SCHEDULER)
                and int(s.RUN_INTERVAL_SECONDS) > 0
                and now >= self._next_due
            )
            if manual or auto_due:
                self._do_run()
                interval = max(int(self.ctx.settings.RUN_INTERVAL_SECONDS), 60)
                self._next_due = time.time() + interval

    def _do_run(self):
        self.running = True
        try:
            summary = self.ctx.recommender.run_once()
            self.last_summary = summary
            self.last_run_ts = time.time()
            log.info(
                "Run complete | movies: %d | series: %d | errors: %d",
                len(summary["movies_added"]),
                len(summary["series_added"]),
                len(summary["errors"]),
            )
        except Exception as e:  # noqa: BLE001
            log.exception("Scheduled run failed: %s", e)
            self.last_summary = {"movies_added": [], "series_added": [], "errors": [str(e)]}
            self.last_run_ts = time.time()
        finally:
            self.running = False
