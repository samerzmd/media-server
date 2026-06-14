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

    def ping(self) -> dict:
        """Validate the API key. Raises on failure."""
        self._get("/configuration")
        return {"ok": True, "detail": "TMDB key valid"}

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

    def find_by_external(self, external_id: str, source: str) -> dict:
        """Resolve an external id to TMDB records.

        source is one of: 'tvdb_id', 'imdb_id'. Returns the raw /find payload
        with movie_results / tv_results lists.
        """
        try:
            return self._get(
                f"/find/{external_id}", params={"external_source": source}
            )
        except requests.RequestException as e:
            log.debug("TMDB find failed for %s=%s: %s", source, external_id, e)
            return {}

    def resolve_tmdb_id(
        self, media_type: str, tvdb: int | None = None, imdb: str | None = None
    ) -> int | None:
        """Find a TMDB id for a series/movie given a TVDB or IMDb id."""
        results_key = "tv_results" if media_type == "tv" else "movie_results"
        if tvdb is not None:
            data = self.find_by_external(str(tvdb), "tvdb_id")
            for r in data.get(results_key, []):
                if r.get("id"):
                    return int(r["id"])
        if imdb:
            data = self.find_by_external(imdb, "imdb_id")
            for r in data.get(results_key, []):
                if r.get("id"):
                    return int(r["id"])
        return None

    def tv_external_ids(self, tmdb_id: int) -> dict:
        """Return external ids (tvdb_id, imdb_id) for a TMDB TV id."""
        try:
            return self._get(f"/tv/{tmdb_id}/external_ids")
        except requests.RequestException as e:
            log.debug("TMDB tv external_ids failed for %s: %s", tmdb_id, e)
            return {}
