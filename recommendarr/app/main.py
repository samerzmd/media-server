"""Entry point: serves the web dashboard and optionally runs the auto-add scheduler."""
import logging
import sys
import threading
import time

from .config import Config
from .jellyfin import JellyfinClient
from .radarr import RadarrClient
from .recommender import Recommender
from .sonarr import SonarrClient
from .state import State
from .tmdb import TMDBClient


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def build_recommender() -> Recommender:
    jellyfin = JellyfinClient(Config.JELLYFIN_URL, Config.JELLYFIN_API_KEY)
    tmdb = TMDBClient(Config.TMDB_API_KEY, Config.TMDB_LANGUAGE)
    radarr = (
        RadarrClient(Config.RADARR_URL, Config.RADARR_API_KEY)
        if Config.RADARR_API_KEY
        else None
    )
    sonarr = (
        SonarrClient(Config.SONARR_URL, Config.SONARR_API_KEY)
        if Config.SONARR_API_KEY
        else None
    )
    state = State(Config.STATE_PATH)
    return Recommender(jellyfin, tmdb, radarr, sonarr, state)


def main():
    setup_logging()
    log = logging.getLogger("recommendarr")

    errors = Config.validate()
    if errors:
        for e in errors:
            log.error("Config error: %s", e)
        sys.exit(1)

    log.info(
        "recommendarr starting | web=%s(:%d) | scheduler=%s | dry_run=%s",
        Config.ENABLE_WEB,
        Config.WEB_PORT,
        Config.ENABLE_SCHEDULER,
        Config.DRY_RUN,
    )

    recommender = build_recommender()

    if not Config.ENABLE_WEB and not Config.ENABLE_SCHEDULER:
        log.error("Both ENABLE_WEB and ENABLE_SCHEDULER are off; nothing to do.")
        sys.exit(1)

    # Scheduler runs in a background thread so the web server stays responsive.
    if Config.ENABLE_SCHEDULER:
        t = threading.Thread(target=scheduler_loop, args=(recommender, log), daemon=True)
        t.start()

    if Config.ENABLE_WEB:
        from waitress import serve

        from .web import create_app

        app = create_app(recommender)
        log.info("Serving dashboard on http://%s:%d", Config.WEB_HOST, Config.WEB_PORT)
        serve(app, host=Config.WEB_HOST, port=Config.WEB_PORT, threads=4)
    else:
        # Scheduler-only mode: block the main thread.
        while True:
            time.sleep(3600)


def scheduler_loop(recommender, log):
    while True:
        try:
            summary = recommender.run_once()
            log.info(
                "Auto-run complete | movies added: %d | series added: %d | errors: %d",
                len(summary["movies_added"]),
                len(summary["series_added"]),
                len(summary["errors"]),
            )
            for m in summary["movies_added"]:
                log.info("  + movie: %s", m)
            for s in summary["series_added"]:
                log.info("  + series: %s", s)
            for err in summary["errors"]:
                log.warning("  ! %s", err)
        except Exception as e:  # noqa: BLE001
            log.exception("Auto-run failed: %s", e)

        if Config.RUN_INTERVAL_SECONDS <= 0:
            log.info("RUN_INTERVAL_SECONDS<=0; scheduler will not repeat.")
            break
        time.sleep(Config.RUN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
