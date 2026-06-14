"""Minimal Jellyfin API client.

We use Jellyfin to discover what users have actually watched (and liked), which
becomes the seed set for recommendations. We pull each title's TMDB id from
Jellyfin's ProviderIds so we can cross-reference TMDB directly.
"""
import logging
from typing import Iterable

import requests

log = logging.getLogger("recommendarr.jellyfin")


class JellyfinClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        # Jellyfin accepts the token via header or query param; header is cleanest.
        self.session.headers.update(
            {"X-Emby-Token": api_key, "Accept": "application/json"}
        )

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, params=params or {}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_users(self) -> list[dict]:
        return self._get("/Users")

    def get_watched_items(self, user_id: str, limit: int = 100) -> list[dict]:
        """Return played + favorited Movies/Series for a user, most recent first.

        We combine two signals:
          - IsPlayed=true  : things they finished / watched
          - IsFavorite=true: things they explicitly liked
        Favorites are weighted more heavily by the recommender.
        """
        items: dict[str, dict] = {}

        def _collect(params: dict, weight: int):
            data = self._get(
                f"/Users/{user_id}/Items",
                params={
                    "Recursive": "true",
                    "IncludeItemTypes": "Movie,Series",
                    "Fields": "ProviderIds,Genres,UserData",
                    "SortBy": "DatePlayed,SortName",
                    "SortOrder": "Descending",
                    "Limit": limit,
                    "EnableTotalRecordCount": "false",
                    **params,
                },
            )
            for it in data.get("Items", []):
                key = it.get("Id")
                if not key:
                    continue
                if key in items:
                    items[key]["_weight"] = max(items[key]["_weight"], weight)
                else:
                    it["_weight"] = weight
                    items[key] = it

        try:
            _collect({"IsPlayed": "true"}, weight=1)
        except requests.RequestException as e:
            log.warning("Failed to fetch played items for user %s: %s", user_id, e)
        try:
            _collect({"IsFavorite": "true"}, weight=3)
        except requests.RequestException as e:
            log.warning("Failed to fetch favorites for user %s: %s", user_id, e)

        return list(items.values())

    def collect_seeds(
        self, user_ids: Iterable[str] | None, per_user_limit: int
    ) -> list[dict]:
        """Gather seed titles across the requested users (or all users)."""
        if user_ids:
            target_ids = list(user_ids)
        else:
            target_ids = [u["Id"] for u in self.get_users()]
            log.info("No JELLYFIN_USER_IDS set; scanning all %d users", len(target_ids))

        seeds: list[dict] = []
        for uid in target_ids:
            watched = self.get_watched_items(uid, limit=per_user_limit)
            log.info("User %s: %d watched/favorited seed items", uid, len(watched))
            seeds.extend(watched)
        return seeds

    @staticmethod
    def _provider(item: dict, *keys: str) -> str | None:
        provider = item.get("ProviderIds") or {}
        # Provider id keys are case-inconsistent across Jellyfin versions.
        lowered = {k.lower(): v for k, v in provider.items()}
        for k in keys:
            val = lowered.get(k.lower())
            if val:
                return str(val)
        return None

    @staticmethod
    def tmdb_id(item: dict) -> int | None:
        raw = JellyfinClient._provider(item, "Tmdb", "TmdbId")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def tvdb_id(item: dict) -> int | None:
        raw = JellyfinClient._provider(item, "Tvdb", "TvdbId")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def imdb_id(item: dict) -> str | None:
        # IMDb ids look like "tt1234567"
        return JellyfinClient._provider(item, "Imdb", "ImdbId")
