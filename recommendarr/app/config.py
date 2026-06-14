"""Configuration loaded from environment variables."""
import os


def _bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _csv(key: str) -> list[str]:
    raw = os.getenv(key, "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


class Config:
    # --- Jellyfin ---
    JELLYFIN_URL = os.getenv("JELLYFIN_URL", "http://jellyfin:8096").rstrip("/")
    JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY", "")
    # Restrict to specific Jellyfin user IDs (empty = all users)
    JELLYFIN_USER_IDS = _csv("JELLYFIN_USER_IDS")

    # --- TMDB ---
    TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
    TMDB_LANGUAGE = os.getenv("TMDB_LANGUAGE", "en-US")

    # --- Radarr (movies) ---
    RADARR_URL = os.getenv("RADARR_URL", "http://radarr:7878").rstrip("/")
    RADARR_API_KEY = os.getenv("RADARR_API_KEY", "")
    # Numeric quality profile id; if unset we resolve a profile by name below
    RADARR_QUALITY_PROFILE_ID = _int("RADARR_QUALITY_PROFILE_ID", 0)
    RADARR_QUALITY_PROFILE_NAME = os.getenv("RADARR_QUALITY_PROFILE_NAME", "")
    RADARR_ROOT_FOLDER = os.getenv("RADARR_ROOT_FOLDER", "/media/movies")
    RADARR_MIN_AVAILABILITY = os.getenv("RADARR_MIN_AVAILABILITY", "released")

    # --- Sonarr (TV) ---
    SONARR_URL = os.getenv("SONARR_URL", "http://sonarr:8989").rstrip("/")
    SONARR_API_KEY = os.getenv("SONARR_API_KEY", "")
    SONARR_QUALITY_PROFILE_ID = _int("SONARR_QUALITY_PROFILE_ID", 0)
    SONARR_QUALITY_PROFILE_NAME = os.getenv("SONARR_QUALITY_PROFILE_NAME", "")
    SONARR_ROOT_FOLDER = os.getenv("SONARR_ROOT_FOLDER", "/media/tv")
    SONARR_LANGUAGE_PROFILE_ID = _int("SONARR_LANGUAGE_PROFILE_ID", 0)
    SONARR_MONITOR = os.getenv("SONARR_MONITOR", "all")

    # --- Recommendation behavior ---
    # How many top movie / TV recommendations to add per run
    MAX_MOVIE_ADDS = _int("MAX_MOVIE_ADDS", 5)
    MAX_TV_ADDS = _int("MAX_TV_ADDS", 3)
    # Minimum TMDB vote average to consider a candidate
    MIN_VOTE_AVERAGE = float(os.getenv("MIN_VOTE_AVERAGE", "6.0"))
    # Minimum number of TMDB votes (filters out obscure / unrated noise)
    MIN_VOTE_COUNT = _int("MIN_VOTE_COUNT", 100)
    # How many recently-watched items to seed recommendations from
    SEED_LIMIT = _int("SEED_LIMIT", 30)
    # Only trigger downloads after auto-add (False = monitor without searching)
    SEARCH_ON_ADD = _bool("SEARCH_ON_ADD", True)
    # When True, log what WOULD be added but don't actually add anything
    DRY_RUN = _bool("DRY_RUN", False)

    # --- Web dashboard ---
    ENABLE_WEB = _bool("ENABLE_WEB", True)
    WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
    WEB_PORT = _int("WEB_PORT", 5000)

    # --- Scheduler ---
    # When False, no automatic adds happen — UI review/approve only.
    ENABLE_SCHEDULER = _bool("ENABLE_SCHEDULER", False)
    # Seconds between runs. 0 = run once and exit.
    RUN_INTERVAL_SECONDS = _int("RUN_INTERVAL_SECONDS", 86400)
    # Where to persist the "already recommended" history
    STATE_PATH = os.getenv("STATE_PATH", "/data/recommendarr_state.json")

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

    @classmethod
    def validate(cls) -> list[str]:
        """Return a list of missing-required-config error messages."""
        errors = []
        if not cls.JELLYFIN_API_KEY:
            errors.append("JELLYFIN_API_KEY is required")
        if not cls.TMDB_API_KEY:
            errors.append("TMDB_API_KEY is required")
        if not cls.RADARR_API_KEY and not cls.SONARR_API_KEY:
            errors.append("At least one of RADARR_API_KEY / SONARR_API_KEY is required")
        return errors
