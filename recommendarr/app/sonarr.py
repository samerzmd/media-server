"""Minimal Sonarr v3 API client for looking up + adding series."""
import logging

import requests

log = logging.getLogger("recommendarr.sonarr")


class SonarrClient:
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
        """TMDB ids already present in the Sonarr library."""
        ids = set()
        for s in self._get("/series"):
            tid = s.get("tmdbId")
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

    def lookup_by_tmdb(self, tmdb_id: int) -> dict | None:
        # Sonarr's series lookup is term-based; tmdb: prefix is supported.
        results = self._get("/series/lookup", params={"term": f"tmdb:{tmdb_id}"})
        if isinstance(results, list) and results:
            return results[0]
        return None

    def add_series(
        self,
        tmdb_id: int,
        quality_profile_id: int,
        root_folder: str,
        language_profile_id: int = 0,
        monitor: str = "all",
        search_on_add: bool = True,
    ) -> dict:
        series = self.lookup_by_tmdb(tmdb_id)
        if not series:
            raise ValueError(f"Sonarr could not look up tmdbId={tmdb_id}")
        payload = {
            "tvdbId": series.get("tvdbId"),
            "title": series.get("title"),
            "titleSlug": series.get("titleSlug"),
            "images": series.get("images", []),
            "seasons": series.get("seasons", []),
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder,
            "monitored": True,
            "addOptions": {
                "monitor": monitor,
                "searchForMissingEpisodes": search_on_add,
            },
        }
        # Newer Sonarr (v4) dropped language profiles; only send when provided.
        if language_profile_id:
            payload["languageProfileId"] = language_profile_id
        return self._post("/series", json=payload)
