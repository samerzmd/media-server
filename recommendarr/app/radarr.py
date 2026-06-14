"""Minimal Radarr v3 API client for looking up + adding movies."""
import logging

import requests

log = logging.getLogger("recommendarr.radarr")


class RadarrClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_key, "Accept": "application/json"})

    def _get(self, path: str, params: dict | None = None):
        resp = self.session.get(
            f"{self.base_url}/api/v3{path}", params=params or {}, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json: dict):
        resp = self.session.post(
            f"{self.base_url}/api/v3{path}", json=json, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def existing_tmdb_ids(self) -> set[int]:
        """TMDB ids already present in the Radarr library."""
        ids = set()
        for m in self._get("/movie"):
            tid = m.get("tmdbId")
            if tid:
                ids.add(int(tid))
        return ids

    def resolve_quality_profile_id(self, name: str) -> int | None:
        for p in self._get("/qualityprofile"):
            if p.get("name", "").lower() == name.lower():
                return p.get("id")
        return None

    def first_quality_profile_id(self) -> int | None:
        profiles = self._get("/qualityprofile")
        return profiles[0]["id"] if profiles else None

    def lookup(self, tmdb_id: int) -> dict | None:
        results = self._get("/movie/lookup/tmdb", params={"tmdbId": tmdb_id})
        if isinstance(results, list):
            return results[0] if results else None
        return results or None

    def add_movie(
        self,
        tmdb_id: int,
        quality_profile_id: int,
        root_folder: str,
        min_availability: str = "released",
        search_on_add: bool = True,
    ) -> dict:
        movie = self.lookup(tmdb_id)
        if not movie:
            raise ValueError(f"Radarr could not look up tmdbId={tmdb_id}")
        payload = {
            "tmdbId": tmdb_id,
            "title": movie.get("title"),
            "year": movie.get("year"),
            "titleSlug": movie.get("titleSlug"),
            "images": movie.get("images", []),
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder,
            "minimumAvailability": min_availability,
            "monitored": True,
            "addOptions": {"searchForMovie": search_on_add},
        }
        return self._post("/movie", json=payload)
