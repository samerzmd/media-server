"""Application context: single source of truth for settings, state, and clients.

Holds the live Settings, the persisted State, the four API clients, and the
Recommender. When connection settings change, clients are rebuilt in place so the
running web server picks them up without a restart.
"""
import logging

from .config import Config
from .jellyfin import JellyfinClient
from .radarr import RadarrClient
from .recommender import Recommender
from .settings import CONNECTION_KEYS, Settings
from .sonarr import SonarrClient
from .state import State
from .tmdb import TMDBClient

log = logging.getLogger("recommendarr.context")


class AppContext:
    def __init__(self):
        self.settings = Settings(Config.SETTINGS_PATH)
        self.state = State(Config.STATE_PATH)
        self.jellyfin = None
        self.tmdb = None
        self.radarr = None
        self.sonarr = None
        self.recommender = None
        self.build_clients()

    def build_clients(self):
        s = self.settings
        self.jellyfin = JellyfinClient(s.JELLYFIN_URL, s.JELLYFIN_API_KEY)
        self.tmdb = TMDBClient(s.TMDB_API_KEY, Config.TMDB_LANGUAGE)
        self.radarr = RadarrClient(s.RADARR_URL, s.RADARR_API_KEY) if s.RADARR_API_KEY else None
        self.sonarr = SonarrClient(s.SONARR_URL, s.SONARR_API_KEY) if s.SONARR_API_KEY else None
        self.recommender = Recommender(
            self.jellyfin, self.tmdb, self.radarr, self.sonarr, self.state, s
        )
        log.info(
            "Clients built | radarr=%s sonarr=%s",
            bool(self.radarr),
            bool(self.sonarr),
        )

    def apply_settings(self, data: dict) -> list[str]:
        """Persist a settings update and rebuild clients if a connection changed."""
        changed = self.settings.update(data)
        if any(k in CONNECTION_KEYS for k in changed):
            self.build_clients()
        return changed

    def test_connections(self) -> dict:
        """Ping each configured service; return per-service status."""
        results = {}
        checks = [
            ("jellyfin", self.jellyfin),
            ("tmdb", self.tmdb),
            ("radarr", self.radarr),
            ("sonarr", self.sonarr),
        ]
        for name, client in checks:
            if client is None:
                results[name] = {"ok": None, "detail": "not configured"}
                continue
            try:
                results[name] = client.ping()
            except Exception as e:  # noqa: BLE001
                results[name] = {"ok": False, "detail": str(e)}
        return results
