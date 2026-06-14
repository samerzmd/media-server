"""Core recommendation engine.

Pipeline:
  1. Pull watched/favorited Movies + Series from Jellyfin (the "seeds").
  2. For each seed, ask TMDB for its recommendations (+similar) list.
  3. Aggregate candidates, scoring each by:
       - how often it was recommended across seeds (co-occurrence),
       - the weight of the seed it came from (favorites count more),
       - its TMDB popularity / vote average.
  4. Drop anything already in the Jellyfin library, already in Radarr/Sonarr,
     or already added by us in a previous run, plus low-rated / low-vote noise.
  5. Add the top N movies to Radarr and top N series to Sonarr.
"""
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from .config import Config

log = logging.getLogger("recommendarr.engine")


@dataclass
class Candidate:
    tmdb_id: int
    media_type: str  # "movie" or "tv"
    title: str
    year: str | None = None
    vote_average: float = 0.0
    vote_count: int = 0
    popularity: float = 0.0
    poster_path: str | None = None
    overview: str = ""
    score: float = 0.0
    seed_hits: int = 0
    contributing_seeds: set[int] = field(default_factory=set)

    def to_dict(self) -> dict:
        poster = (
            f"https://image.tmdb.org/t/p/w342{self.poster_path}"
            if self.poster_path
            else None
        )
        tmdb_url = (
            f"https://www.themoviedb.org/{'movie' if self.media_type == 'movie' else 'tv'}/{self.tmdb_id}"
        )
        return {
            "tmdb_id": self.tmdb_id,
            "media_type": self.media_type,
            "title": self.title,
            "year": self.year,
            "vote_average": round(self.vote_average, 1),
            "vote_count": self.vote_count,
            "poster": poster,
            "overview": self.overview,
            "score": round(self.score, 2),
            "seed_hits": self.seed_hits,
            "tmdb_url": tmdb_url,
        }


def _title_of(item: dict, media_type: str) -> str:
    if media_type == "movie":
        return item.get("title") or item.get("original_title") or "Unknown"
    return item.get("name") or item.get("original_name") or "Unknown"


def _year_of(item: dict, media_type: str) -> str | None:
    date = item.get("release_date") if media_type == "movie" else item.get("first_air_date")
    if date and len(date) >= 4:
        return date[:4]
    return None


class Recommender:
    def __init__(self, jellyfin, tmdb, radarr, sonarr, state, settings=None):
        self.jellyfin = jellyfin
        self.tmdb = tmdb
        self.radarr = radarr
        self.sonarr = sonarr
        self.state = state
        # Runtime settings (env defaults + UI overrides). Falls back to Config.
        self.settings = settings or Config

    def _user_ids(self):
        s = self.settings
        if hasattr(s, "user_id_list"):
            return s.user_id_list() or None
        return s.JELLYFIN_USER_IDS or None

    # ---- step 1+2+3: build the candidate pool ----
    def build_candidates(self) -> tuple[dict[int, Candidate], set[int], set[int]]:
        seeds = self.jellyfin.collect_seeds(
            self._user_ids(), per_user_limit=self.settings.SEED_LIMIT
        )

        # TMDB ids already in the user's library — never recommend these back.
        library_movie_ids: set[int] = set()
        library_series_ids: set[int] = set()

        candidates: dict[int, Candidate] = {}

        # Diagnostics: many Jellyfin series only carry a TVDB id, not a TMDB id,
        # so we resolve those via TMDB's /find. Track how seeds break down.
        stats = {
            "movie_seeds": 0,
            "tv_seeds": 0,
            "tv_resolved": 0,
            "seeds_no_id": 0,
        }

        for seed in seeds:
            jf_type = (seed.get("Type") or "").lower()
            media_type = "movie" if jf_type == "movie" else "tv"
            weight = seed.get("_weight", 1)

            seed_tmdb = self.jellyfin.tmdb_id(seed)
            if seed_tmdb is None:
                # Resolve via external ids (TVDB primary for series, IMDb fallback).
                tvdb = self.jellyfin.tvdb_id(seed)
                imdb = self.jellyfin.imdb_id(seed)
                if tvdb is not None or imdb:
                    seed_tmdb = self.tmdb.resolve_tmdb_id(media_type, tvdb=tvdb, imdb=imdb)
                    if seed_tmdb is not None and media_type == "tv":
                        stats["tv_resolved"] += 1
            if seed_tmdb is None:
                stats["seeds_no_id"] += 1
                continue

            if media_type == "movie":
                stats["movie_seeds"] += 1
            else:
                stats["tv_seeds"] += 1

            if media_type == "movie":
                library_movie_ids.add(seed_tmdb)
            else:
                library_series_ids.add(seed_tmdb)

            recs = self.tmdb.recommendations(media_type, seed_tmdb)
            if not recs:
                recs = self.tmdb.similar(media_type, seed_tmdb)

            for rank, rec in enumerate(recs):
                rid = rec.get("id")
                if rid is None:
                    continue
                rid = int(rid)
                cand = candidates.get(rid)
                if cand is None:
                    cand = Candidate(
                        tmdb_id=rid,
                        media_type=media_type,
                        title=_title_of(rec, media_type),
                        year=_year_of(rec, media_type),
                        vote_average=float(rec.get("vote_average") or 0.0),
                        vote_count=int(rec.get("vote_count") or 0),
                        popularity=float(rec.get("popularity") or 0.0),
                        poster_path=rec.get("poster_path"),
                        overview=rec.get("overview") or "",
                    )
                    candidates[rid] = cand
                # Position bias: earlier in TMDB's list = stronger signal.
                position_weight = 1.0 / (1 + rank)
                cand.score += weight * position_weight
                cand.seed_hits += 1
                cand.contributing_seeds.add(seed_tmdb)

        log.info(
            "Seeds: %d movie, %d tv (%d tv resolved via TVDB/IMDb), %d had no usable id",
            stats["movie_seeds"],
            stats["tv_seeds"],
            stats["tv_resolved"],
            stats["seeds_no_id"],
        )

        # Final score blends co-occurrence with TMDB quality signals.
        for cand in candidates.values():
            cand.score = (
                cand.score
                + 0.15 * cand.vote_average
                + 0.0005 * min(cand.popularity, 1000)
            )

        return candidates, library_movie_ids, library_series_ids

    # ---- step 4: filter ----
    def _filter(
        self,
        candidates: dict[int, Candidate],
        media_type: str,
        library_ids: set[int],
        already_in_arr: set[int],
        already_added: set[int],
    ) -> list[Candidate]:
        out = []
        for cand in candidates.values():
            if cand.media_type != media_type:
                continue
            if cand.tmdb_id in library_ids:
                continue
            if cand.tmdb_id in already_in_arr:
                continue
            if cand.tmdb_id in already_added:
                continue
            if cand.vote_average < self.settings.MIN_VOTE_AVERAGE:
                continue
            if cand.vote_count < self.settings.MIN_VOTE_COUNT:
                continue
            out.append(cand)
        out.sort(key=lambda c: (c.score, c.vote_average, c.vote_count), reverse=True)
        return out

    # ---- UI: ranked recommendations without adding ----
    def get_recommendations(self, limit_per_type: int = 60) -> dict:
        """Return filtered, ranked movie + TV candidates for the dashboard."""
        candidates, lib_movies, lib_series = self.build_candidates()

        movie_arr = set()
        if self.radarr:
            try:
                movie_arr = self.radarr.existing_tmdb_ids()
            except Exception as e:  # noqa: BLE001
                log.warning("Radarr library fetch failed: %s", e)
        tv_arr = set()
        if self.sonarr:
            try:
                tv_arr = self.sonarr.existing_tmdb_ids()
            except Exception as e:  # noqa: BLE001
                log.warning("Sonarr library fetch failed: %s", e)

        movies = self._filter(candidates, "movie", lib_movies, movie_arr, self.state.added_movies)
        tv = self._filter(candidates, "tv", lib_series, tv_arr, self.state.added_series)
        return {
            "movies": [c.to_dict() for c in movies[:limit_per_type]],
            "tv": [c.to_dict() for c in tv[:limit_per_type]],
        }

    # ---- UI: add a single title on demand ----
    def add_one(self, media_type: str, tmdb_id: int) -> dict:
        tmdb_id = int(tmdb_id)
        if media_type == "movie":
            if not self.radarr:
                return {"ok": False, "error": "Radarr not configured"}
            qp = self._radarr_profile()
            if qp is None:
                return {"ok": False, "error": "No Radarr quality profile available"}
            try:
                self.radarr.add_movie(
                    tmdb_id,
                    quality_profile_id=qp,
                    root_folder=self.settings.RADARR_ROOT_FOLDER,
                    min_availability=Config.RADARR_MIN_AVAILABILITY,
                    search_on_add=self.settings.SEARCH_ON_ADD,
                )
                self.state.added_movies.add(tmdb_id)
                self.state.save()
                return {"ok": True}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": str(e)}
        elif media_type == "tv":
            if not self.sonarr:
                return {"ok": False, "error": "Sonarr not configured"}
            qp = self._sonarr_profile()
            if qp is None:
                return {"ok": False, "error": "No Sonarr quality profile available"}
            try:
                ext = self.tmdb.tv_external_ids(tmdb_id)
                tvdb = ext.get("tvdb_id")
                self.sonarr.add_series(
                    tmdb_id,
                    quality_profile_id=qp,
                    root_folder=self.settings.SONARR_ROOT_FOLDER,
                    tvdb_id=int(tvdb) if tvdb else None,
                    language_profile_id=Config.SONARR_LANGUAGE_PROFILE_ID,
                    monitor=Config.SONARR_MONITOR,
                    search_on_add=self.settings.SEARCH_ON_ADD,
                )
                self.state.added_series.add(tmdb_id)
                self.state.save()
                return {"ok": True}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": str(e)}
        return {"ok": False, "error": f"Unknown media_type: {media_type}"}

    def dismiss(self, media_type: str, tmdb_id: int) -> dict:
        """Mark a recommendation as seen so it won't resurface."""
        tmdb_id = int(tmdb_id)
        if media_type == "movie":
            self.state.added_movies.add(tmdb_id)
        else:
            self.state.added_series.add(tmdb_id)
        self.state.save()
        return {"ok": True}

    # ---- step 5: add (batch / scheduler) ----
    def run_once(self) -> dict:
        summary = {"movies_added": [], "series_added": [], "errors": []}

        candidates, lib_movies, lib_series = self.build_candidates()
        log.info("Built %d candidate titles from seeds", len(candidates))

        # ---- Movies via Radarr ----
        if self.radarr and self.settings.MAX_MOVIE_ADDS > 0:
            try:
                arr_ids = self.radarr.existing_tmdb_ids()
            except Exception as e:  # noqa: BLE001
                arr_ids = set()
                summary["errors"].append(f"Radarr library fetch failed: {e}")
            qp = self._radarr_profile()
            ranked = self._filter(
                candidates, "movie", lib_movies, arr_ids, self.state.added_movies
            )
            for cand in ranked[: self.settings.MAX_MOVIE_ADDS]:
                label = f"{cand.title} ({cand.year or '?'}) [tmdb:{cand.tmdb_id}] score={cand.score:.2f}"
                if self.settings.DRY_RUN:
                    log.info("[DRY RUN] would add MOVIE: %s", label)
                    summary["movies_added"].append(label + " (dry-run)")
                    continue
                if qp is None:
                    summary["errors"].append("No Radarr quality profile available")
                    break
                try:
                    self.radarr.add_movie(
                        cand.tmdb_id,
                        quality_profile_id=qp,
                        root_folder=self.settings.RADARR_ROOT_FOLDER,
                        min_availability=Config.RADARR_MIN_AVAILABILITY,
                        search_on_add=self.settings.SEARCH_ON_ADD,
                    )
                    self.state.added_movies.add(cand.tmdb_id)
                    summary["movies_added"].append(label)
                    log.info("Added MOVIE to Radarr: %s", label)
                except Exception as e:  # noqa: BLE001
                    summary["errors"].append(f"Radarr add failed for {label}: {e}")
                    log.warning("Radarr add failed for %s: %s", label, e)

        # ---- TV via Sonarr ----
        if self.sonarr and self.settings.MAX_TV_ADDS > 0:
            try:
                arr_ids = self.sonarr.existing_tmdb_ids()
            except Exception as e:  # noqa: BLE001
                arr_ids = set()
                summary["errors"].append(f"Sonarr library fetch failed: {e}")
            qp = self._sonarr_profile()
            ranked = self._filter(
                candidates, "tv", lib_series, arr_ids, self.state.added_series
            )
            for cand in ranked[: self.settings.MAX_TV_ADDS]:
                label = f"{cand.title} ({cand.year or '?'}) [tmdb:{cand.tmdb_id}] score={cand.score:.2f}"
                if self.settings.DRY_RUN:
                    log.info("[DRY RUN] would add SERIES: %s", label)
                    summary["series_added"].append(label + " (dry-run)")
                    continue
                if qp is None:
                    summary["errors"].append("No Sonarr quality profile available")
                    break
                try:
                    ext = self.tmdb.tv_external_ids(cand.tmdb_id)
                    tvdb = ext.get("tvdb_id")
                    self.sonarr.add_series(
                        cand.tmdb_id,
                        quality_profile_id=qp,
                        root_folder=self.settings.SONARR_ROOT_FOLDER,
                        tvdb_id=int(tvdb) if tvdb else None,
                        language_profile_id=Config.SONARR_LANGUAGE_PROFILE_ID,
                        monitor=Config.SONARR_MONITOR,
                        search_on_add=self.settings.SEARCH_ON_ADD,
                    )
                    self.state.added_series.add(cand.tmdb_id)
                    summary["series_added"].append(label)
                    log.info("Added SERIES to Sonarr: %s", label)
                except Exception as e:  # noqa: BLE001
                    summary["errors"].append(f"Sonarr add failed for {label}: {e}")
                    log.warning("Sonarr add failed for %s: %s", label, e)

        if not self.settings.DRY_RUN:
            self.state.save()
        return summary

    def _radarr_profile(self) -> int | None:
        if Config.RADARR_QUALITY_PROFILE_ID:
            return Config.RADARR_QUALITY_PROFILE_ID
        try:
            if self.settings.RADARR_QUALITY_PROFILE_NAME:
                pid = self.radarr.resolve_quality_profile_id(
                    self.settings.RADARR_QUALITY_PROFILE_NAME
                )
                if pid:
                    return pid
            return self.radarr.first_quality_profile_id()
        except Exception as e:  # noqa: BLE001
            log.warning("Could not resolve Radarr quality profile: %s", e)
            return None

    def _sonarr_profile(self) -> int | None:
        if Config.SONARR_QUALITY_PROFILE_ID:
            return Config.SONARR_QUALITY_PROFILE_ID
        try:
            if self.settings.SONARR_QUALITY_PROFILE_NAME:
                pid = self.sonarr.resolve_quality_profile_id(
                    self.settings.SONARR_QUALITY_PROFILE_NAME
                )
                if pid:
                    return pid
            return self.sonarr.first_quality_profile_id()
        except Exception as e:  # noqa: BLE001
            log.warning("Could not resolve Sonarr quality profile: %s", e)
            return None
