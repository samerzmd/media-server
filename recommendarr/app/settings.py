"""Runtime settings: env-var defaults overlaid with UI edits persisted to /data.

The dashboard can change behavior without editing docker-compose. Editable fields
are declared in FIELD_SPECS (also drives the settings form). Values are read at
runtime via attribute access, e.g. ``settings.MAX_MOVIE_ADDS``.
"""
import json
import logging
import os

from .config import Config

log = logging.getLogger("recommendarr.settings")

# (key, type, group, label, secret)
#   type: int | float | bool | str
#   secret: True -> value masked in API responses (API keys, etc.)
FIELD_SPECS = [
    # --- Recommendation tuning ---
    ("MAX_MOVIE_ADDS", "int", "Recommendation tuning", "Max movies added per run", False),
    ("MAX_TV_ADDS", "int", "Recommendation tuning", "Max TV shows added per run", False),
    ("MIN_VOTE_AVERAGE", "float", "Recommendation tuning", "Minimum TMDB rating (0–10)", False),
    ("MIN_VOTE_COUNT", "int", "Recommendation tuning", "Minimum TMDB vote count", False),
    ("SEED_LIMIT", "int", "Recommendation tuning", "Watched items per user to seed from", False),
    # --- Library targets ---
    ("RADARR_ROOT_FOLDER", "str", "Library targets", "Radarr root folder", False),
    ("RADARR_QUALITY_PROFILE_NAME", "str", "Library targets", "Radarr quality profile (name; blank = first)", False),
    ("SONARR_ROOT_FOLDER", "str", "Library targets", "Sonarr root folder", False),
    ("SONARR_QUALITY_PROFILE_NAME", "str", "Library targets", "Sonarr quality profile (name; blank = first)", False),
    ("SEARCH_ON_ADD", "bool", "Library targets", "Search for downloads immediately on add", False),
    # --- Automation ---
    ("ENABLE_SCHEDULER", "bool", "Automation", "Enable automatic adds on a schedule", False),
    ("RUN_INTERVAL_SECONDS", "int", "Automation", "Seconds between automatic runs", False),
    ("DRY_RUN", "bool", "Automation", "Dry run (simulate adds, change nothing)", False),
    # --- Connections ---
    ("JELLYFIN_URL", "str", "Connections", "Jellyfin URL", False),
    ("JELLYFIN_API_KEY", "str", "Connections", "Jellyfin API key", True),
    ("JELLYFIN_USER_IDS", "str", "Connections", "Jellyfin user IDs (comma-separated; blank = all)", False),
    ("TMDB_API_KEY", "str", "Connections", "TMDB API key", True),
    ("RADARR_URL", "str", "Connections", "Radarr URL", False),
    ("RADARR_API_KEY", "str", "Connections", "Radarr API key", True),
    ("SONARR_URL", "str", "Connections", "Sonarr URL", False),
    ("SONARR_API_KEY", "str", "Connections", "Sonarr API key", True),
]

_TYPES = {k: t for k, t, *_ in FIELD_SPECS}
_SECRET = {k for k, _, _, _, secret in FIELD_SPECS if secret}
EDITABLE_KEYS = [k for k, *_ in FIELD_SPECS]

# Keys whose change requires rebuilding the API clients.
CONNECTION_KEYS = {
    "JELLYFIN_URL", "JELLYFIN_API_KEY", "TMDB_API_KEY",
    "RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY",
}


def _coerce(key: str, value):
    t = _TYPES[key]
    if t == "int":
        return int(value)
    if t == "float":
        return float(value)
    if t == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return "" if value is None else str(value).strip()


class Settings:
    def __init__(self, path: str = None):
        self.path = path or Config.SETTINGS_PATH
        # Defaults sourced from Config (env vars / built-in defaults).
        defaults = {}
        for key in EDITABLE_KEYS:
            if key == "JELLYFIN_USER_IDS":
                defaults[key] = ",".join(Config.JELLYFIN_USER_IDS)
            else:
                defaults[key] = getattr(Config, key)
        object.__setattr__(self, "_values", defaults)
        self._load_overlay()

    def _load_overlay(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for key, val in saved.items():
                if key in self._values:
                    try:
                        self._values[key] = _coerce(key, val)
                    except (TypeError, ValueError):
                        log.warning("Ignoring bad saved value for %s", key)
            log.info("Loaded %d saved setting override(s) from %s", len(saved), self.path)
        except (OSError, ValueError) as e:
            log.warning("Could not read settings file %s: %s", self.path, e)

    def __getattr__(self, name):
        values = object.__getattribute__(self, "_values")
        if name in values:
            return values[name]
        raise AttributeError(name)

    def user_id_list(self) -> list[str]:
        raw = self._values.get("JELLYFIN_USER_IDS", "") or ""
        return [x.strip() for x in raw.split(",") if x.strip()]

    def update(self, data: dict) -> list[str]:
        """Apply a partial update. Returns the list of keys that changed."""
        changed = []
        for key, val in data.items():
            if key not in self._values:
                continue
            try:
                new = _coerce(key, val)
            except (TypeError, ValueError):
                log.warning("Rejected invalid value for %s: %r", key, val)
                continue
            if new != self._values[key]:
                self._values[key] = new
                changed.append(key)
        if changed:
            self.save()
        return changed

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._values, f, indent=2)
        except OSError as e:
            log.warning("Could not write settings file %s: %s", self.path, e)

    def as_form(self) -> list[dict]:
        """Field metadata + current values for rendering the settings form.

        Secrets are not returned; instead a boolean flag indicates whether a value
        is set, so the UI can show a 'leave blank to keep' placeholder.
        """
        out = []
        for key, t, group, label, secret in FIELD_SPECS:
            entry = {"key": key, "type": t, "group": group, "label": label, "secret": secret}
            if secret:
                entry["is_set"] = bool(self._values.get(key))
            else:
                entry["value"] = self._values.get(key)
            out.append(entry)
        return out
