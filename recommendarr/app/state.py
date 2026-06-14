"""Tiny JSON-file state store to remember what we've already recommended.

This prevents re-adding (or re-suggesting) the same title every run, and avoids
fighting the user if they intentionally deleted something we added before.
"""
import json
import logging
import os

log = logging.getLogger("recommendarr.state")


class State:
    def __init__(self, path: str):
        self.path = path
        self.added_movies: set[int] = set()
        self.added_series: set[int] = set()
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.added_movies = set(int(x) for x in data.get("added_movies", []))
            self.added_series = set(int(x) for x in data.get("added_series", []))
            log.info(
                "Loaded state: %d movies, %d series previously added",
                len(self.added_movies),
                len(self.added_series),
            )
        except (OSError, ValueError) as e:
            log.warning("Could not read state file %s: %s", self.path, e)

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "added_movies": sorted(self.added_movies),
                        "added_series": sorted(self.added_series),
                    },
                    f,
                    indent=2,
                )
        except OSError as e:
            log.warning("Could not write state file %s: %s", self.path, e)
