"""Minimal Jellyfin API client.

We use Jellyfin to discover what users have actually watched (and liked), which
becomes the seed set for recommendations. We pull each title's TMDB id from
Jellyfin's ProviderIds so we can cross-reference TMDB directly.
"""
import logging
from collections import Counter
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

    def get_watched_items(
        self, user_id: str, limit: int = 100, item_types: str = "Movie,Series"
    ) -> list[dict]:
        """Return played + favorited items of the given type(s), most recent first.

        We combine two signals:
          - IsPlayed=true  : things they finished / watched
          - IsFavorite=true: things they explicitly liked
        Favorites are weighted more heavily by the recommender.

        item_types should be a single type group (e.g. "Movie" or "Series") so the
        per-type limit is applied independently — otherwise a movie-heavy history
        can crowd out series entirely.
        """
        items: dict[str, dict] = {}

        def _collect(params: dict, weight: int):
            data = self._get(
                f"/Users/{user_id}/Items",
                params={
                    "Recursive": "true",
                    "IncludeItemTypes": item_types,
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
            log.warning("Failed to fetch played %s for user %s: %s", item_types, user_id, e)
        try:
            _collect({"IsFavorite": "true"}, weight=3)
        except requests.RequestException as e:
            log.warning("Failed to fetch favorite %s for user %s: %s", item_types, user_id, e)

        return list(items.values())

    def get_seed_series(
        self, user_id: str, limit: int = 60, episode_scan: int = 600
    ) -> list[dict]:
        """Discover series the user actually engaged with.

        Jellyfin only marks a *Series* played when every episode is watched, and
        favorited only on explicit action, so relying on series-level flags misses
        most real viewing. We therefore combine three signals:
          - favorited series           (weight 3)
          - fully-played series        (weight 2)
          - series with watched episodes, rolled up by SeriesId (weight 1)
        Returned items always carry ProviderIds for downstream TMDB resolution.
        """
        result: dict[str, dict] = {}

        def _add(item: dict, weight: int):
            sid = item.get("Id")
            if not sid:
                return
            if sid in result:
                result[sid]["_weight"] = max(result[sid]["_weight"], weight)
            else:
                item["_weight"] = weight
                result[sid] = item

        # 1) Series-level flags (favorite > fully played)
        for params, weight in (({"IsFavorite": "true"}, 3), ({"IsPlayed": "true"}, 2)):
            try:
                data = self._get(
                    f"/Users/{user_id}/Items",
                    params={
                        "Recursive": "true",
                        "IncludeItemTypes": "Series",
                        "Fields": "ProviderIds",
                        "SortBy": "DatePlayed,SortName",
                        "SortOrder": "Descending",
                        "Limit": limit,
                        "EnableTotalRecordCount": "false",
                        **params,
                    },
                )
                for it in data.get("Items", []):
                    _add(it, weight)
            except requests.RequestException as e:
                log.warning("Series-flag query failed for user %s: %s", user_id, e)

        # 2) Watched episodes -> parent series (the signal that usually matters)
        try:
            data = self._get(
                f"/Users/{user_id}/Items",
                params={
                    "Recursive": "true",
                    "IncludeItemTypes": "Episode",
                    "IsPlayed": "true",
                    "Fields": "SeriesId",
                    "SortBy": "DatePlayed",
                    "SortOrder": "Descending",
                    "Limit": episode_scan,
                    "EnableTotalRecordCount": "false",
                },
            )
            counts: Counter = Counter()
            for ep in data.get("Items", []):
                sid = ep.get("SeriesId")
                if sid:
                    counts[sid] += 1
            missing = [sid for sid in counts if sid not in result]
            # Batch-fetch ProviderIds for series we only know via episodes.
            for chunk_start in range(0, len(missing), 50):
                chunk = missing[chunk_start : chunk_start + 50]
                try:
                    sdata = self._get(
                        f"/Users/{user_id}/Items",
                        params={
                            "Ids": ",".join(chunk),
                            "Fields": "ProviderIds",
                            "EnableTotalRecordCount": "false",
                        },
                    )
                    for it in sdata.get("Items", []):
                        _add(it, 1)
                except requests.RequestException as e:
                    log.warning("Series detail fetch failed for user %s: %s", user_id, e)
        except requests.RequestException as e:
            log.warning("Watched-episode query failed for user %s: %s", user_id, e)

        return list(result.values())

    def collect_seeds(
        self, user_ids: Iterable[str] | None, per_user_limit: int
    ) -> list[dict]:
        """Gather seed titles across the requested users (or all users).

        Movies and series are gathered independently (so one type can't starve the
        other), and series are discovered from watched *episodes*, not just
        fully-played/favorited series.
        """
        if user_ids:
            target_ids = list(user_ids)
        else:
            target_ids = [u["Id"] for u in self.get_users()]
            log.info("No JELLYFIN_USER_IDS set; scanning all %d users", len(target_ids))

        seeds: list[dict] = []
        for uid in target_ids:
            movies = self.get_watched_items(uid, limit=per_user_limit, item_types="Movie")
            series = self.get_seed_series(uid, limit=per_user_limit)
            log.info(
                "User %s: %d movie + %d series seed items", uid, len(movies), len(series)
            )
            seeds.extend(movies)
            seeds.extend(series)
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
