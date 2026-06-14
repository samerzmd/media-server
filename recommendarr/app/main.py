"""Entry point: builds the app context, starts the scheduler, serves the web app."""
import logging
import os
import secrets
import sys
import time

from .config import Config
from .context import AppContext
from .scheduler import Scheduler


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _secret_key() -> str:
    """Stable Flask secret key: env var, else a persisted random key."""
    if Config.SECRET_KEY:
        return Config.SECRET_KEY
    path = Config.SECRET_PATH
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        key = secrets.token_hex(32)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(key)
        return key
    except OSError:
        # Falls back to an ephemeral key (sessions reset on restart).
        return secrets.token_hex(32)


def main():
    setup_logging()
    log = logging.getLogger("recommendarr")

    errors = Config.validate()
    if errors:
        for e in errors:
            log.error("Config error: %s", e)
        sys.exit(1)

    if Config.APP_PASSWORD == "changeme":
        log.warning("APP_PASSWORD is the default 'changeme' — set APP_PASSWORD!")

    ctx = AppContext()
    scheduler = Scheduler(ctx)
    scheduler.start()

    log.info(
        "recommendarr ready | web=%s(:%d) | scheduler_enabled=%s | dry_run=%s",
        Config.ENABLE_WEB,
        Config.WEB_PORT,
        ctx.settings.ENABLE_SCHEDULER,
        ctx.settings.DRY_RUN,
    )

    if Config.ENABLE_WEB:
        from waitress import serve

        from .web import create_app

        app = create_app(ctx, scheduler, _secret_key())
        log.info("Serving on http://%s:%d", Config.WEB_HOST, Config.WEB_PORT)
        serve(app, host=Config.WEB_HOST, port=Config.WEB_PORT, threads=4)
    else:
        log.info("Web disabled; running scheduler-only.")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
