"""arr-themed web dashboard for reviewing & approving recommendations.

Servarr dark theme: movies use Radarr gold, TV uses Sonarr blue.
Recommendations are cached in memory (building them hits TMDB a lot) and can be
refreshed on demand with the Refresh button.
"""
import logging
import threading
import time

from flask import Flask, jsonify, request

from .config import Config

log = logging.getLogger("recommendarr.web")

_cache = {"data": None, "ts": 0.0}
_lock = threading.Lock()
CACHE_TTL = 1800  # 30 min


def create_app(recommender) -> Flask:
    app = Flask(__name__)

    def _get_recs(refresh: bool = False):
        with _lock:
            fresh = (
                _cache["data"] is not None
                and not refresh
                and (time.time() - _cache["ts"]) < CACHE_TTL
            )
            if fresh:
                return _cache["data"]
            log.info("Building recommendations for dashboard (refresh=%s)", refresh)
            data = recommender.get_recommendations()
            _cache["data"] = data
            _cache["ts"] = time.time()
            return data

    @app.get("/")
    def index():
        return PAGE

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True})

    @app.get("/api/recommendations")
    def api_recommendations():
        refresh = request.args.get("refresh") == "1"
        try:
            data = _get_recs(refresh=refresh)
            return jsonify(
                {
                    "ok": True,
                    "generated_at": _cache["ts"],
                    "dry_run": Config.DRY_RUN,
                    **data,
                }
            )
        except Exception as e:  # noqa: BLE001
            log.exception("Failed to build recommendations")
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.post("/api/add")
    def api_add():
        body = request.get_json(force=True, silent=True) or {}
        mt = body.get("media_type")
        tmdb_id = body.get("tmdb_id")
        if mt not in ("movie", "tv") or tmdb_id is None:
            return jsonify({"ok": False, "error": "media_type and tmdb_id required"}), 400
        if Config.DRY_RUN:
            return jsonify({"ok": True, "dry_run": True})
        result = recommender.add_one(mt, int(tmdb_id))
        code = 200 if result.get("ok") else 502
        return jsonify(result), code

    @app.post("/api/dismiss")
    def api_dismiss():
        body = request.get_json(force=True, silent=True) or {}
        mt = body.get("media_type")
        tmdb_id = body.get("tmdb_id")
        if mt not in ("movie", "tv") or tmdb_id is None:
            return jsonify({"ok": False, "error": "media_type and tmdb_id required"}), 400
        return jsonify(recommender.dismiss(mt, int(tmdb_id)))

    return app


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Recommendarr</title>
<style>
  :root {
    --bg: #1c1c1c;
    --bg-elev: #232323;
    --card: #2a2a2a;
    --card-hover: #313131;
    --border: #353535;
    --text: #e1e1e1;
    --muted: #909090;
    --radarr: #ffc230;   /* movies */
    --sonarr: #35c5f4;   /* tv */
    --accent: #35c5f4;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 14px;
  }
  header {
    background: var(--bg-elev);
    border-bottom: 1px solid var(--border);
    padding: 14px 22px;
    display: flex;
    align-items: center;
    gap: 14px;
    position: sticky;
    top: 0;
    z-index: 10;
  }
  .logo {
    font-size: 20px; font-weight: 700; letter-spacing: .5px;
  }
  .logo .a { color: var(--radarr); }
  .logo .b { color: var(--sonarr); }
  .spacer { flex: 1; }
  .badge {
    font-size: 11px; text-transform: uppercase; letter-spacing: .5px;
    padding: 3px 8px; border-radius: 3px; border: 1px solid var(--border);
    color: var(--muted);
  }
  .badge.dry { color: #1c1c1c; background: var(--radarr); border-color: var(--radarr); font-weight: 700; }
  button {
    font-family: inherit; cursor: pointer; border-radius: 4px;
    border: 1px solid var(--border); background: var(--card); color: var(--text);
    padding: 7px 14px; font-size: 13px; transition: background .12s, border-color .12s;
  }
  button:hover { background: var(--card-hover); }
  button:disabled { opacity: .55; cursor: default; }
  .tabs { display: flex; gap: 6px; padding: 16px 22px 0; }
  .tab {
    padding: 9px 18px; border: 1px solid var(--border); border-bottom: none;
    border-radius: 6px 6px 0 0; background: var(--bg-elev); color: var(--muted);
    cursor: pointer; font-weight: 600;
  }
  .tab.active.movie { color: var(--radarr); border-color: var(--radarr); }
  .tab.active.tv    { color: var(--sonarr); border-color: var(--sonarr); }
  .count { color: var(--muted); font-weight: 400; font-size: 12px; margin-left: 6px; }
  .wrap { padding: 18px 22px 60px; }
  .grid {
    display: grid; gap: 16px;
    grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  }
  .card {
    background: var(--card); border: 1px solid var(--border); border-radius: 8px;
    overflow: hidden; display: flex; flex-direction: column;
  }
  .poster { aspect-ratio: 2/3; background: #181818 center/cover no-repeat; position: relative; }
  .poster .noimg { display:flex; align-items:center; justify-content:center; height:100%; color:#555; font-size:12px;}
  .rating {
    position: absolute; top: 8px; left: 8px; background: rgba(0,0,0,.78);
    border-radius: 4px; padding: 2px 7px; font-size: 12px; font-weight: 700;
  }
  .movie .rating { color: var(--radarr); }
  .tv .rating { color: var(--sonarr); }
  .meta { padding: 10px 12px; flex: 1; display:flex; flex-direction:column; }
  .title { font-weight: 600; font-size: 13.5px; line-height: 1.25; }
  .sub { color: var(--muted); font-size: 12px; margin-top: 3px; }
  .ov { color: #b0b0b0; font-size: 11.5px; margin-top: 8px;
        display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  .actions { display: flex; gap: 6px; padding: 0 12px 12px; }
  .add { flex: 1; font-weight: 700; color: #1c1c1c; border: none; }
  .movie .add { background: var(--radarr); }
  .tv .add { background: var(--sonarr); }
  .add:hover { filter: brightness(1.08); }
  .add.done { background: #3a3a3a !important; color: var(--muted); }
  .dismiss { padding: 7px 10px; }
  .empty, .loading { color: var(--muted); padding: 50px 0; text-align: center; }
  a.link { color: inherit; text-decoration: none; }
  a.link:hover .title { text-decoration: underline; }
</style>
</head>
<body>
<header>
  <span class="logo"><span class="a">Recommend</span><span class="b">arr</span></span>
  <span id="dry" class="badge" style="display:none">Dry run</span>
  <span class="spacer"></span>
  <span id="ts" class="badge"></span>
  <button id="refresh">↻ Refresh</button>
</header>

<div class="tabs">
  <div class="tab movie active" data-tab="movie">Movies <span class="count" id="cm"></span></div>
  <div class="tab tv" data-tab="tv">TV <span class="count" id="ct"></span></div>
</div>

<div class="wrap">
  <div id="movie" class="grid"></div>
  <div id="tv" class="grid" style="display:none"></div>
  <div id="status" class="loading">Loading recommendations…</div>
</div>

<script>
let DATA = {movie: [], tv: []};
let DRY = false;
let active = "movie";

function setActive(t) {
  active = t;
  document.querySelectorAll(".tab").forEach(e => e.classList.toggle("active", e.dataset.tab === t));
  document.getElementById("movie").style.display = t === "movie" ? "grid" : "none";
  document.getElementById("tv").style.display = t === "tv" ? "grid" : "none";
}
document.querySelectorAll(".tab").forEach(e => e.onclick = () => setActive(e.dataset.tab));

function card(item, type) {
  const el = document.createElement("div");
  el.className = "card " + type;
  const poster = item.poster
    ? `<div class="poster" style="background-image:url('${item.poster}')"><span class="rating">★ ${item.vote_average}</span></div>`
    : `<div class="poster"><div class="noimg">no poster</div><span class="rating">★ ${item.vote_average}</span></div>`;
  el.innerHTML = `
    ${poster}
    <div class="meta">
      <a class="link" href="${item.tmdb_url}" target="_blank" rel="noopener">
        <div class="title">${item.title}</div>
      </a>
      <div class="sub">${item.year || ''} · ${item.vote_count.toLocaleString()} votes · seen in ${item.seed_hits}</div>
      <div class="ov">${(item.overview || '').replace(/</g,'&lt;')}</div>
    </div>
    <div class="actions">
      <button class="add">${DRY ? 'Add (dry)' : '+ Add'}</button>
      <button class="dismiss" title="Hide this">✕</button>
    </div>`;
  const addBtn = el.querySelector(".add");
  addBtn.onclick = async () => {
    addBtn.disabled = true; addBtn.textContent = "…";
    const r = await post("/api/add", {media_type: type, tmdb_id: item.tmdb_id});
    if (r.ok) { addBtn.textContent = DRY ? "Would add ✓" : "Added ✓"; addBtn.classList.add("done"); }
    else { addBtn.disabled = false; addBtn.textContent = "Retry"; alert("Add failed: " + (r.error||"")); }
  };
  el.querySelector(".dismiss").onclick = async () => {
    await post("/api/dismiss", {media_type: type, tmdb_id: item.tmdb_id});
    el.remove();
  };
  return el;
}

async function post(url, body) {
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
  return r.json();
}

function render() {
  for (const type of ["movie", "tv"]) {
    const grid = document.getElementById(type);
    grid.innerHTML = "";
    DATA[type].forEach(i => grid.appendChild(card(i, type)));
  }
  document.getElementById("cm").textContent = DATA.movie.length;
  document.getElementById("ct").textContent = DATA.tv.length;
}

async function load(refresh) {
  const status = document.getElementById("status");
  status.style.display = "block";
  status.textContent = refresh ? "Rebuilding from your watch history…" : "Loading recommendations…";
  try {
    const r = await fetch("/api/recommendations" + (refresh ? "?refresh=1" : ""));
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "error");
    DATA = {movie: j.movies || [], tv: j.tv || []};
    DRY = !!j.dry_run;
    document.getElementById("dry").style.display = DRY ? "inline-block" : "none";
    document.getElementById("dry").className = "badge dry";
    if (j.generated_at) {
      const d = new Date(j.generated_at * 1000);
      document.getElementById("ts").textContent = "Updated " + d.toLocaleTimeString();
    }
    render();
    const total = DATA.movie.length + DATA.tv.length;
    status.style.display = total ? "none" : "block";
    if (!total) status.textContent = "No new recommendations right now. Watch more in Jellyfin, then Refresh.";
  } catch (e) {
    status.textContent = "Failed to load: " + e.message;
  }
}

document.getElementById("refresh").onclick = () => load(true);
load(false);
</script>
</body>
</html>"""
