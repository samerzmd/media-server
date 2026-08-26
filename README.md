# media-server

A self-hosted media stack: it finds things, downloads them, names them, subtitles
them — including translating Arabic subtitles that don't exist anywhere — and
streams them. One `docker compose up` on a single box.

Everything runs as UID/GID `1000` against one storage mount, so every service
sees the same files at the same paths. That last part matters more than it
sounds: half the wiring below only works because Bazarr and tarjem agree on what
`/media/tv` means.

---

## What's in it

| Service | Port | What it does |
|---|---|---|
| **Jellyfin** | 8096 | The player. Streams the library to TVs, phones, browsers |
| **Sonarr** | 8989 | TV: watches for new episodes, sends them to the downloader, renames them |
| **Radarr** | 7878 | The same, for films |
| **Readarr** | 8787 | The same, for books |
| **Prowlarr** | 9696 | Indexer manager. Configure trackers once here, it pushes them to the *arrs |
| **qBittorrent** | 8080 | The downloader everything hands work to |
| **Bazarr** | 6767 | Hunts subtitles for whatever Sonarr and Radarr bring in |
| **tarjem** | 8081 | AI Arabic subtitles, for when Bazarr finds none ([own repo](https://github.com/samerzmd/tarjem)) |
| **subgen** | 9000 | Whisper transcription — a last resort when a file has no text subtitle at all |
| **Calibre-Web** | 8083 | Reads the book library Readarr fills |
| **recommendarr** | 8089 | Reads Jellyfin history, suggests things via TMDB, adds approved picks to Radarr/Sonarr |
| **commandarr** | — | Telegram bot for requesting things without opening a browser ¹ |
| **File Browser** | 8082 | Web file manager over the whole storage mount |
| **Nginx Proxy Manager** | 80 / 81 / 443 | Reverse proxy and Let's Encrypt certificates |
| **OpenVPN** | 943 / 9443 / 1194 | Remote access into the LAN |

¹ commandarr is the one service not currently wired up: its compose block
declares no `networks:`, so it lands on the default network while Sonarr and
Radarr are on `media_network`, and `SONARR_URL: sonarr` cannot resolve from
there. Adding `networks: [media_network]` to that block fixes it.

---

## How the pieces fit

```
                    ┌───────────┐
   you ask ────────>│  Sonarr   │ TV
                    │  Radarr   │ films        ┌─────────────┐
                    │  Readarr  │ books ──────>│  Prowlarr   │ which trackers
                    └─────┬─────┘              └─────────────┘
                          │ send to downloader
                          v
                    ┌───────────┐
                    │qBittorrent│
                    └─────┬─────┘
                          │ done -> import, rename, move into place
                          v
                 /mnt/storage/media
                          │
            ┌─────────────┼──────────────┐
            v             v              v
      ┌──────────┐  ┌──────────┐   ┌──────────┐
      │ Jellyfin │  │  Bazarr  │   │ Calibre  │
      │  (watch) │  │ (subs)   │   │  (read)  │
      └──────────┘  └────┬─────┘   └──────────┘
                         │ found English, no Arabic
                         v
                    ┌──────────┐      writes Episode.ar.srt beside the video,
                    │  tarjem  │ ───> then tells Bazarr to rescan so it shows up
                    └──────────┘
```

`recommendarr` closes the loop: it reads what you actually watched in Jellyfin
and proposes the next things to feed back into Radarr and Sonarr.

---

## Requirements

- Docker and the Compose plugin
- A storage mount at `/mnt/storage` (change the paths in `docker-compose.yml` if
  yours lives elsewhere — but change them *everywhere*, see the gotcha below)
- A user with UID/GID `1000` owning that mount
- An NVIDIA GPU if you want tarjem to translate locally at a usable speed.
  Everything else runs fine without one.

---

## Setup

**1. Clone, and clone tarjem beside it.** tarjem is a separate repository and is
built from source, so it has to sit next to this one — not inside it:

```bash
git clone https://github.com/samerzmd/media-server.git
git clone https://github.com/samerzmd/tarjem.git
cd media-server
```

```
parent/
├── media-server/     <- you are here
└── tarjem/           <- built by the tarjem service
```

**2. Fill in the secrets.**

```bash
cp .env.example .env
```

Most API keys don't exist yet — that's expected. Start the stack, collect them
from each service's settings page, then put them in `.env` and restart. The ones
that are needed up front are `RECOMMENDARR_PASSWORD`, `TARJEM_PASSWORD` and
`TARJEM_TOKEN`.

**3. Create the directories the containers write to.**

```bash
mkdir -p tarjem_data && sudo chown 1000:1000 tarjem_data
mkdir -p subgen/models filebrowser_database
touch filebrowser_database/database.db
```

**4. Start it.**

```bash
docker compose up -d
```

First run pulls a lot of images and builds two of them; give it a while.

---

## Wiring it together

Compose starts the containers. It does not configure them — that part is manual,
once, in each web UI.

**Prowlarr → the *arrs.** Add your indexers in Prowlarr, then add Sonarr, Radarr
and Readarr under *Settings → Apps*. Prowlarr pushes indexers out to all three,
so you never configure a tracker more than once. Use the compose service names
as hostnames: `http://sonarr:8989`, not an IP.

**The *arrs → qBittorrent.** In each, *Settings → Download Clients → qBittorrent*,
host `qbittorrent`, port `8080`.

**Root folders.** Sonarr `/media/tv`, Radarr `/media/movies`, Readarr
`/media/books`. These are the in-container paths, and they must match what the
compose file mounts.

**Bazarr → Sonarr and Radarr.** Point Bazarr at both, then add subtitle
providers and a language profile. If you want Arabic via tarjem, make the
profile ask for **English** — tarjem translates from whatever Bazarr finds, so a
profile that only wants Arabic gives it nothing to work with.

**Bazarr → tarjem.** In *Settings → Subtitles → Post-processing*, enable it and
call tarjem's webhook so a newly downloaded English subtitle is translated
immediately. tarjem's README has the exact command; it also sweeps the library
on a timer, so this is an optimisation rather than a requirement.

**Jellyfin.** Add `/media/movies` and `/media/tv` as libraries. Sidecar `.srt`
files are picked up automatically, tarjem's Arabic ones included.

---

## Storage layout

```
/mnt/storage/
├── media/
│   ├── Movies/         -> /media/movies   (radarr, bazarr, tarjem, jellyfin)
│   ├── TV Shows/       -> /media/tv       (sonarr, bazarr, tarjem, jellyfin)
│   └── Books/          -> /media/books    (readarr, calibre-web)
└── qbittorrent/        -> /downloads      (qbittorrent + every *arr)
```

Service config lives in `./<service>_config` directories next to the compose
file. They are gitignored — they hold API keys, sessions and databases.

**The gotcha:** a container path must be identical everywhere it appears.
Bazarr's post-processing hook hands tarjem a path like
`/media/tv/Show/Season 1/Episode.mkv`, and tarjem opens that exact string. If
the two mount the same directory under different names, every hand-off silently
fails. This is why `/mnt/storage/media` is mounted three ways for some services
— it is deliberate, not leftovers.

---

## Remote access

Three options, in order of how much you should trust them:

- **OpenVPN** (`943`) — the safe one. You're on the LAN; nothing is exposed.
- **Nginx Proxy Manager** (`81`) — reverse proxy with Let's Encrypt certs, for
  services you deliberately publish. Put authentication in front of anything you
  expose.
- **Cloudflare Tunnel** — not in this compose file; runs on the host and needs
  no open inbound ports at all.

Don't publish qBittorrent, File Browser or the *arrs. They have no meaningful
authentication story and File Browser can see the entire storage mount.

---

## Day to day

```bash
docker compose ps                      # what's running
docker compose logs -f sonarr          # follow one service
docker compose pull && docker compose up -d    # update everything
docker compose up -d --build tarjem    # rebuild tarjem after a git pull
docker compose restart bazarr          # restart one
```

Updating tarjem means pulling *its* repo, then rebuilding here:

```bash
(cd ../tarjem && git pull) && docker compose up -d --build tarjem
```

---

## Backups

Worth keeping: `.env`, and the `*_config/` directories — they hold your
indexers, quality profiles, watch history and API keys. Rebuilding those by hand
is a bad evening.

Not worth keeping: the media itself (re-downloadable) and `subgen/models`
(re-downloadable, and large).

---

## License

[MIT](LICENSE) — covers what's in this repository: the compose file, the
configuration, and the `recommendarr` service built from source here.

It does not cover the software it runs. Sonarr, Radarr, Prowlarr, Bazarr,
Jellyfin, qBittorrent and the rest are third-party images pulled at runtime,
each under its own licence.
