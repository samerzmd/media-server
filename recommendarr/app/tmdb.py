"""Minimal TMDB API client (v3).

Given a seed movie/show's TMDB id, fetch TMDB's own "recommendations" list, which
is a strong, well-maintained similarity signal. We aggregate these across all
seeds to build a ranked candidate pool.
"""
import logging

import requests

log = logging.getLogger("recommendarr.tmdb")

BASE = "https://api.themoviedb.org/3"


class TMDBClient:
    def __init__(self, api_key: str, language: str = "en-US", timeout: int = 30):
        self.api_key = api_key
        self.language = language
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path: str, params: dict | None = None) -> dict:
        p = {"api_key": self.api_key, "language": self.language}
        if params:
            p.update(params)
        resp = self.session.get(f"{BASE}{path}", params=p, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def recommendations(self, media_type: str, tmdb_id: int) -> list[dict]:
        """media_type is 'movie' or 'tv'. Returns the results list."""
        try:
            data = self._get(f"/{media_type}/{tmdb_id}/recommendations")
            return data.get("results", [])
        except requests.RequestException as e:
            log.debug("TMDB recommendations failed for %s/%s: %s", media_type, tmdb_id, e)
            return []

    def similar(self, media_type: str, tmdb_id: int) -> list[dict]:
        try:
            data = self._get(f"/{media_type}/{tmdb_id}/similar")
            return data.get("results", [])
        except requests.RequestException as e:
            log.debug("TMDB similar failed for %s/%s: %s", media_type, tmdb_id, e)
            return []
