# recommendarr

A small Python service that turns your **Jellyfin** watch history into download
requests in **Radarr** (movies) and **Sonarr** (TV) — via a *arr-themed
**review & approve dashboard**, an optional fully-automatic scheduler, or both.

## The dashboard

A servarr-styled dark UI (movies in Radarr gold, TV in Sonarr blue) at
**http://your-host:8089**, behind a **username/password login**. It shows ranked
recommendations as a poster grid; each card has TMDB rating, year, vote count, and
how many of your watched titles it was recommended from. Click **+ Add** to send a
title to Radarr/Sonarr (and trigger a search), or **✕** to hide it so it won't
resurface. **Refresh** rebuilds the list from your latest watch history (cached ~30 min).

## Login

Set `RECOMMENDARR_USER` / `RECOMMENDARR_PASSWORD` in your `.env` (defaults to
`admin` / `changeme` — change them). Sessions are signed with `RECOMMENDARR_SECRET_KEY`
if set, otherwise an auto-generated key persisted in `/data`.

## Settings page

Everything below can be edited live from **Settings** (no restart) and is saved to
`/data/settings.json`, overriding the env defaults:

- **Recommendation tuning** — max movie/TV adds, min vote average, min vote count, seed limit.
- **Library targets** — Radarr/Sonarr root folder + quality profile name, search-on-add.
- **Automation** — enable scheduler, run interval, dry-run, plus a **Run now** button.
- **Connections** — Jellyfin/TMDB/Radarr/Sonarr URLs + API keys, with **Test connections**.

Changing a connection rebuilds the relevant client immediately. API keys are write-only
in the form (blank = keep the existing value).

## How it works

```
Jellyfin watch history / favorites
        │  (TMDB ids via ProviderIds)
        ▼
   TMDB recommendations + similar  ── aggregate & score ──┐
        │                                                 │
        ▼                                                 ▼
  drop titles already in your library / *arr / added before
        │
        ├──► top N movies ──► Radarr  (lookup + add + search)
        └──► top N series ──► Sonarr  (lookup + add + search)
```

Each run it:

1. Pulls every **played** and **favorited** Movie/Series from Jellyfin (favorites
   are weighted 3× as a stronger taste signal).
2. Asks TMDB for each seed's `recommendations` (falling back to `similar`).
3. Scores candidates by cross-seed co-occurrence + position in TMDB's list +
   TMDB vote average and popularity.
4. Filters out anything already in your Jellyfin library, already in Radarr/Sonarr,
   already added by a previous run, or below the rating/vote thresholds.
5. Adds the top `MAX_MOVIE_ADDS` movies and `MAX_TV_ADDS` series, optionally
   triggering an immediate search.

State (what it has already added) is persisted to `/data/recommendarr_state.json`
so it never re-adds the same title and won't fight you if you delete something.

## Setup

1. **Get the API keys** and put them in your repo `.env` (see `.env.example`):
   - `JELLYFIN_API_KEY` — Jellyfin Dashboard → Advanced → API Keys → **+**
   - `TMDB_API_KEY` — https://www.themoviedb.org/settings/api (the v3 key)
   - `RADARR_API_KEY` / `SONARR_API_KEY` — already in your `.env`

2. **Build and start**, then open the dashboard at **http://your-host:8089**:

   ```bash
   docker compose up -d --build recommendarr
   docker compose logs -f recommendarr
   ```

   It ships in **review & approve** mode (`ENABLE_WEB=true`,
   `ENABLE_SCHEDULER=false`): nothing is added until you click **+ Add**.

### Optional: fully automatic mode

Set `ENABLE_SCHEDULER: "true"` to also auto-add the top `MAX_MOVIE_ADDS` /
`MAX_TV_ADDS` picks every `RUN_INTERVAL_SECONDS`. Set `DRY_RUN: "true"` to make
both the Add buttons and the scheduler only simulate (logged, not sent).

## Configuration

All via environment variables (set in `docker-compose.yml`).

| Variable | Default | Description |
|---|---|---|
| `ENABLE_WEB` | `true` | Serve the review/approve dashboard |
| `WEB_PORT` | `5000` | In-container port (mapped to `8089` on host) |
| `ENABLE_SCHEDULER` | `false` | Also auto-add top picks on an interval |
| `JELLYFIN_URL` | `http://jellyfin:8096` | Jellyfin base URL |
| `JELLYFIN_API_KEY` | — | **Required** |
| `JELLYFIN_USER_IDS` | *(all)* | Comma-separated user IDs to scan |
| `TMDB_API_KEY` | — | **Required** |
| `RADARR_URL` / `RADARR_API_KEY` | `http://radarr:7878` | Movie target |
| `SONARR_URL` / `SONARR_API_KEY` | `http://sonarr:8989` | TV target |
| `RADARR_ROOT_FOLDER` | `/media/movies` | Must match Radarr's root folder |
| `SONARR_ROOT_FOLDER` | `/media/tv` | Must match Sonarr's root folder |
| `RADARR_QUALITY_PROFILE_NAME` | *(first)* | Profile by name; else first profile |
| `SONARR_QUALITY_PROFILE_NAME` | *(first)* | Profile by name; else first profile |
| `MAX_MOVIE_ADDS` | `5` | Movies added per run |
| `MAX_TV_ADDS` | `3` | Series added per run |
| `MIN_VOTE_AVERAGE` | `6.0` | Skip lower-rated candidates |
| `MIN_VOTE_COUNT` | `100` | Skip obscure/unrated candidates |
| `SEED_LIMIT` | `30` | Recent watched items per user to seed from |
| `SEARCH_ON_ADD` | `true` | Trigger download search immediately |
| `DRY_RUN` | `false`* | Log intended adds without acting |
| `RUN_INTERVAL_SECONDS` | `86400` | Seconds between runs; `0` = run once |

\* The compose file defaults `DRY_RUN` to `true` for safety; flip it after review.

## Notes

- At least one of Radarr/Sonarr must be configured; the other can be omitted.
- Quality profile and root folder are auto-resolved if you don't pin them, but
  pinning is recommended once you know your setup.
- **Trakt** can be added later as an alternative/additional source: implement a
  client mirroring `tmdb.py` and feed its results into `recommender.build_candidates`.
  TMDB was chosen here because it needs only a free key and your Jellyfin items
  already carry TMDB ids.
