"""arr-themed web app: login, review/approve dashboard, and settings page.

Servarr dark theme — movies in Radarr gold, TV in Sonarr blue. All routes require
a logged-in session except the login form and health check.
"""
import hmac
import logging
import threading
import time

from flask import (
    Flask,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

from .config import Config

log = logging.getLogger("recommendarr.web")

_cache = {"data": None, "ts": 0.0}
_lock = threading.Lock()
CACHE_TTL = 1800  # 30 min


def create_app(ctx, scheduler, secret_key: str) -> Flask:
    app = Flask(__name__)
    app.secret_key = secret_key
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

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
            data = ctx.recommender.get_recommendations()
            _cache["data"] = data
            _cache["ts"] = time.time()
            return data

    # ---------------- auth ----------------
    @app.before_request
    def require_login():
        path = request.path
        if path == "/healthz" or path == "/login" or path.startswith("/static"):
            return None
        if session.get("user"):
            return None
        if path.startswith("/api/"):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = request.form.get("username", "")
            pw = request.form.get("password", "")
            ok_user = hmac.compare_digest(user, Config.APP_USERNAME)
            ok_pw = hmac.compare_digest(pw, Config.APP_PASSWORD)
            if ok_user and ok_pw:
                session["user"] = user
                return redirect(url_for("index"))
            return LOGIN_PAGE.replace("<!--ERROR-->", "Invalid credentials"), 401
        if session.get("user"):
            return redirect(url_for("index"))
        return LOGIN_PAGE.replace("<!--ERROR-->", "")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---------------- pages ----------------
    @app.get("/")
    def index():
        return PAGE

    @app.get("/settings")
    def settings_page():
        return SETTINGS_PAGE

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True})

    # ---------------- dashboard API ----------------
    @app.get("/api/recommendations")
    def api_recommendations():
        refresh = request.args.get("refresh") == "1"
        try:
            data = _get_recs(refresh=refresh)
            return jsonify(
                {
                    "ok": True,
                    "generated_at": _cache["ts"],
                    "dry_run": ctx.settings.DRY_RUN,
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
        if ctx.settings.DRY_RUN:
            return jsonify({"ok": True, "dry_run": True})
        result = ctx.recommender.add_one(mt, int(tmdb_id))
        return jsonify(result), (200 if result.get("ok") else 502)

    @app.post("/api/dismiss")
    def api_dismiss():
        body = request.get_json(force=True, silent=True) or {}
        mt = body.get("media_type")
        tmdb_id = body.get("tmdb_id")
        if mt not in ("movie", "tv") or tmdb_id is None:
            return jsonify({"ok": False, "error": "media_type and tmdb_id required"}), 400
        return jsonify(ctx.recommender.dismiss(mt, int(tmdb_id)))

    # ---------------- settings API ----------------
    @app.get("/api/settings")
    def api_settings_get():
        return jsonify({"ok": True, "fields": ctx.settings.as_form()})

    @app.post("/api/settings")
    def api_settings_post():
        body = request.get_json(force=True, silent=True) or {}
        # Ignore empty secret fields so blank = "keep existing".
        from .settings import _SECRET  # local import to avoid cycle at top

        clean = {}
        for k, v in body.items():
            if k in _SECRET and (v is None or str(v).strip() == ""):
                continue
            clean[k] = v
        changed = ctx.apply_settings(clean)
        # Invalidate the recommendations cache if anything affecting them changed.
        with _lock:
            _cache["data"] = None
        return jsonify({"ok": True, "changed": changed})

    @app.post("/api/test")
    def api_test():
        return jsonify({"ok": True, "results": ctx.test_connections()})

    @app.post("/api/run-now")
    def api_run_now():
        scheduler.run_now()
        return jsonify({"ok": True})

    @app.get("/api/scheduler")
    def api_scheduler():
        return jsonify({"ok": True, **scheduler.status()})

    return app


# ============================ templates ============================

_THEME = """
  :root {
    --bg:#1c1c1c; --bg-elev:#232323; --card:#2a2a2a; --card-hover:#313131;
    --border:#353535; --text:#e1e1e1; --muted:#909090;
    --radarr:#ffc230; --sonarr:#35c5f4; --accent:#35c5f4;
    --ok:#4caf50; --err:#e5534b;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; font-size:14px; }
  header { background:var(--bg-elev); border-bottom:1px solid var(--border);
    padding:14px 22px; display:flex; align-items:center; gap:16px; position:sticky; top:0; z-index:10; }
  .logo { font-size:20px; font-weight:700; letter-spacing:.5px; text-decoration:none; }
  .logo .a { color:var(--radarr); } .logo .b { color:var(--sonarr); }
  .spacer { flex:1; }
  nav a { color:var(--muted); text-decoration:none; margin-left:16px; font-weight:600; }
  nav a:hover, nav a.active { color:var(--text); }
  button, .btn { font-family:inherit; cursor:pointer; border-radius:4px; border:1px solid var(--border);
    background:var(--card); color:var(--text); padding:7px 14px; font-size:13px;
    transition:background .12s,border-color .12s; }
  button:hover, .btn:hover { background:var(--card-hover); }
  button:disabled { opacity:.55; cursor:default; }
  .badge { font-size:11px; text-transform:uppercase; letter-spacing:.5px; padding:3px 8px;
    border-radius:3px; border:1px solid var(--border); color:var(--muted); }
  .badge.dry { color:#1c1c1c; background:var(--radarr); border-color:var(--radarr); font-weight:700; }
"""

LOGIN_PAGE = (
    """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Recommendarr — Login</title>
<style>"""
    + _THEME
    + """
  body { display:flex; align-items:center; justify-content:center; min-height:100vh; }
  .box { background:var(--bg-elev); border:1px solid var(--border); border-radius:10px;
    padding:32px; width:320px; }
  .logo { display:block; text-align:center; font-size:26px; margin-bottom:6px; }
  .tag { text-align:center; color:var(--muted); margin-bottom:22px; font-size:13px; }
  label { display:block; font-size:12px; color:var(--muted); margin:14px 0 5px; }
  input { width:100%; padding:10px; border-radius:5px; border:1px solid var(--border);
    background:var(--card); color:var(--text); font-size:14px; }
  .submit { width:100%; margin-top:22px; font-weight:700; color:#1c1c1c;
    background:var(--sonarr); border:none; padding:11px; }
  .err { color:var(--err); font-size:13px; text-align:center; margin-top:14px; min-height:16px; }
</style></head><body>
  <form class="box" method="POST" action="/login">
    <span class="logo"><span class="a">Recommend</span><span class="b">arr</span></span>
    <div class="tag">Sign in to continue</div>
    <label>Username</label>
    <input name="username" autocomplete="username" autofocus>
    <label>Password</label>
    <input name="password" type="password" autocomplete="current-password">
    <button class="submit" type="submit">Sign in</button>
    <div class="err"><!--ERROR--></div>
  </form>
</body></html>"""
)

_NAV = """
<header>
  <a class="logo" href="/"><span class="a">Recommend</span><span class="b">arr</span></a>
  <nav>
    <a href="/" id="nav-home">Dashboard</a>
    <a href="/settings" id="nav-settings">Settings</a>
  </nav>
  <span class="spacer"></span>
  __EXTRA__
  <form method="POST" action="/logout" style="display:inline"><button type="submit">Log out</button></form>
</header>
"""

PAGE = (
    """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Recommendarr</title>
<style>"""
    + _THEME
    + """
  .tabs { display:flex; gap:6px; padding:16px 22px 0; }
  .tab { padding:9px 18px; border:1px solid var(--border); border-bottom:none; border-radius:6px 6px 0 0;
    background:var(--bg-elev); color:var(--muted); cursor:pointer; font-weight:600; }
  .tab.active.movie { color:var(--radarr); border-color:var(--radarr); }
  .tab.active.tv { color:var(--sonarr); border-color:var(--sonarr); }
  .count { color:var(--muted); font-weight:400; font-size:12px; margin-left:6px; }
  .wrap { padding:18px 22px 60px; }
  .grid { display:grid; gap:16px; grid-template-columns:repeat(auto-fill,minmax(168px,1fr)); }
  .card { background:var(--card); border:1px solid var(--border); border-radius:8px; overflow:hidden;
    display:flex; flex-direction:column; }
  .poster { aspect-ratio:2/3; background:#181818 center/cover no-repeat; position:relative; }
  .poster .noimg { display:flex; align-items:center; justify-content:center; height:100%; color:#555; font-size:12px; }
  .rating { position:absolute; top:8px; left:8px; background:rgba(0,0,0,.78); border-radius:4px;
    padding:2px 7px; font-size:12px; font-weight:700; }
  .movie .rating { color:var(--radarr); } .tv .rating { color:var(--sonarr); }
  .meta { padding:10px 12px; flex:1; display:flex; flex-direction:column; }
  .title { font-weight:600; font-size:13.5px; line-height:1.25; }
  .sub { color:var(--muted); font-size:12px; margin-top:3px; }
  .ov { color:#b0b0b0; font-size:11.5px; margin-top:8px; display:-webkit-box; -webkit-line-clamp:3;
    -webkit-box-orient:vertical; overflow:hidden; }
  .actions { display:flex; gap:6px; padding:0 12px 12px; }
  .add { flex:1; font-weight:700; color:#1c1c1c; border:none; }
  .movie .add { background:var(--radarr); } .tv .add { background:var(--sonarr); }
  .add:hover { filter:brightness(1.08); } .add.done { background:#3a3a3a !important; color:var(--muted); }
  .dismiss { padding:7px 10px; }
  .empty, .loading { color:var(--muted); padding:50px 0; text-align:center; }
  a.link { color:inherit; text-decoration:none; } a.link:hover .title { text-decoration:underline; }
</style></head><body>
"""
    + _NAV.replace("__EXTRA__", '<span id="dry" class="badge" style="display:none">Dry run</span>\n  <span id="ts" class="badge"></span>\n  <button id="refresh">↻ Refresh</button>')
    + """
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
document.getElementById("nav-home").classList.add("active");
let DATA={movie:[],tv:[]}, DRY=false, active="movie";
function setActive(t){active=t;
  document.querySelectorAll(".tab").forEach(e=>e.classList.toggle("active",e.dataset.tab===t));
  document.getElementById("movie").style.display=t==="movie"?"grid":"none";
  document.getElementById("tv").style.display=t==="tv"?"grid":"none";}
document.querySelectorAll(".tab").forEach(e=>e.onclick=()=>setActive(e.dataset.tab));
function card(item,type){const el=document.createElement("div");el.className="card "+type;
  const poster=item.poster
    ?`<div class="poster" style="background-image:url('${item.poster}')"><span class="rating">★ ${item.vote_average}</span></div>`
    :`<div class="poster"><div class="noimg">no poster</div><span class="rating">★ ${item.vote_average}</span></div>`;
  el.innerHTML=`${poster}<div class="meta">
      <a class="link" href="${item.tmdb_url}" target="_blank" rel="noopener"><div class="title">${item.title}</div></a>
      <div class="sub">${item.year||''} · ${item.vote_count.toLocaleString()} votes · seen in ${item.seed_hits}</div>
      <div class="ov">${(item.overview||'').replace(/</g,'&lt;')}</div></div>
    <div class="actions"><button class="add">${DRY?'Add (dry)':'+ Add'}</button>
      <button class="dismiss" title="Hide this">✕</button></div>`;
  const addBtn=el.querySelector(".add");
  addBtn.onclick=async()=>{addBtn.disabled=true;addBtn.textContent="…";
    const r=await post("/api/add",{media_type:type,tmdb_id:item.tmdb_id});
    if(r.ok){addBtn.textContent=DRY?"Would add ✓":"Added ✓";addBtn.classList.add("done");}
    else{addBtn.disabled=false;addBtn.textContent="Retry";alert("Add failed: "+(r.error||""));}};
  el.querySelector(".dismiss").onclick=async()=>{await post("/api/dismiss",{media_type:type,tmdb_id:item.tmdb_id});el.remove();};
  return el;}
async function post(url,body){const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});return r.json();}
function render(){for(const type of ["movie","tv"]){const grid=document.getElementById(type);grid.innerHTML="";
  DATA[type].forEach(i=>grid.appendChild(card(i,type)));}
  document.getElementById("cm").textContent=DATA.movie.length;document.getElementById("ct").textContent=DATA.tv.length;}
async function load(refresh){const status=document.getElementById("status");status.style.display="block";
  status.textContent=refresh?"Rebuilding from your watch history…":"Loading recommendations…";
  try{const r=await fetch("/api/recommendations"+(refresh?"?refresh=1":""));const j=await r.json();
    if(!j.ok)throw new Error(j.error||"error");
    DATA={movie:j.movies||[],tv:j.tv||[]};DRY=!!j.dry_run;
    document.getElementById("dry").style.display=DRY?"inline-block":"none";document.getElementById("dry").className="badge dry";
    if(j.generated_at){document.getElementById("ts").textContent="Updated "+new Date(j.generated_at*1000).toLocaleTimeString();}
    render();const total=DATA.movie.length+DATA.tv.length;status.style.display=total?"none":"block";
    if(!total)status.textContent="No new recommendations right now. Watch more in Jellyfin, then Refresh.";
  }catch(e){status.textContent="Failed to load: "+e.message;}}
document.getElementById("refresh").onclick=()=>load(true);
load(false);
</script></body></html>"""
)

SETTINGS_PAGE = (
    """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Recommendarr — Settings</title>
<style>"""
    + _THEME
    + """
  .wrap { padding:22px; max-width:760px; margin:0 auto; }
  .group { background:var(--bg-elev); border:1px solid var(--border); border-radius:8px;
    padding:18px 20px; margin-bottom:18px; }
  .group h2 { margin:0 0 14px; font-size:15px; }
  .field { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:9px 0;
    border-top:1px solid var(--border); }
  .field:first-of-type { border-top:none; }
  .field label { color:var(--text); font-size:13.5px; flex:1; }
  .field .hint { color:var(--muted); font-size:11.5px; }
  input[type=text], input[type=number], input[type=password] { width:260px; padding:8px;
    border-radius:5px; border:1px solid var(--border); background:var(--card); color:var(--text); font-size:13px; }
  input[type=checkbox] { width:18px; height:18px; }
  .bar { position:sticky; bottom:0; background:var(--bg-elev); border-top:1px solid var(--border);
    padding:14px 22px; display:flex; gap:10px; align-items:center; }
  .save { font-weight:700; color:#1c1c1c; background:var(--sonarr); border:none; padding:9px 18px; }
  .msg { font-size:13px; color:var(--muted); }
  .msg.ok { color:var(--ok); } .msg.err { color:var(--err); }
  .results { font-size:12.5px; margin-left:auto; display:flex; gap:14px; flex-wrap:wrap; }
  .res-ok { color:var(--ok); } .res-err { color:var(--err); } .res-na { color:var(--muted); }
  .sched { color:var(--muted); font-size:12.5px; }
</style></head><body>
"""
    + _NAV.replace("__EXTRA__", "")
    + """
<div class="wrap">
  <div id="form"></div>
  <div class="group">
    <h2>Automation actions</h2>
    <div class="field">
      <div><label>Run the recommender now</label><div class="hint sched" id="sched"></div></div>
      <button id="runnow">▶ Run now</button>
    </div>
  </div>
</div>
<div class="bar">
  <button class="save" id="save">Save settings</button>
  <button id="test">Test connections</button>
  <span class="msg" id="msg"></span>
  <span class="results" id="results"></span>
</div>
<script>
document.getElementById("nav-settings").classList.add("active");
const TYPES={};
async function loadFields(){
  const r=await fetch("/api/settings");const j=await r.json();
  const byGroup={};
  j.fields.forEach(f=>{TYPES[f.key]=f.type;(byGroup[f.group]=byGroup[f.group]||[]).push(f);});
  const root=document.getElementById("form");root.innerHTML="";
  for(const group of Object.keys(byGroup)){
    const g=document.createElement("div");g.className="group";g.innerHTML=`<h2>${group}</h2>`;
    byGroup[group].forEach(f=>{
      const row=document.createElement("div");row.className="field";
      let input;
      if(f.type==="bool"){input=`<input type="checkbox" data-key="${f.key}" ${f.value?"checked":""}>`;}
      else if(f.secret){input=`<input type="password" data-key="${f.key}" placeholder="${f.is_set?'•••••• (leave blank to keep)':'not set'}">`;}
      else if(f.type==="int"||f.type==="float"){input=`<input type="number" step="${f.type==='float'?'0.1':'1'}" data-key="${f.key}" value="${f.value??''}">`;}
      else {input=`<input type="text" data-key="${f.key}" value="${(f.value??'').toString().replace(/"/g,'&quot;')}">`;}
      row.innerHTML=`<label>${f.label}</label>${input}`;
      g.appendChild(row);
    });
    root.appendChild(g);
  }
}
function collect(){
  const out={};
  document.querySelectorAll("[data-key]").forEach(el=>{
    const k=el.dataset.key;
    if(el.type==="checkbox")out[k]=el.checked;
    else if(el.type==="password"){if(el.value!=="")out[k]=el.value;}
    else out[k]=el.value;
  });
  return out;
}
function setMsg(t,cls){const m=document.getElementById("msg");m.textContent=t;m.className="msg "+(cls||"");}
document.getElementById("save").onclick=async()=>{
  setMsg("Saving…");
  const r=await fetch("/api/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(collect())});
  const j=await r.json();
  if(j.ok){setMsg("Saved "+(j.changed.length)+" change(s).","ok");loadFields();refreshSched();}
  else setMsg("Save failed: "+(j.error||""),"err");
};
document.getElementById("test").onclick=async()=>{
  setMsg("Testing…");
  const r=await fetch("/api/test",{method:"POST"});const j=await r.json();
  const res=document.getElementById("results");res.innerHTML="";
  for(const [name,v] of Object.entries(j.results||{})){
    const cls=v.ok===true?"res-ok":(v.ok===false?"res-err":"res-na");
    const mark=v.ok===true?"✓":(v.ok===false?"✗":"—");
    const span=document.createElement("span");span.className=cls;
    span.textContent=`${mark} ${name}: ${v.detail}`;res.appendChild(span);
  }
  setMsg("");
};
async function refreshSched(){
  const r=await fetch("/api/scheduler");const j=await r.json();
  const last=j.last_run_ts?("last run "+new Date(j.last_run_ts*1000).toLocaleString()):"never run";
  document.getElementById("sched").textContent=`Scheduler ${j.enabled?"enabled":"disabled"} · every ${j.interval}s · ${last}${j.running?" · running…":""}`;
}
document.getElementById("runnow").onclick=async()=>{
  const b=document.getElementById("runnow");b.disabled=true;b.textContent="Started…";
  await fetch("/api/run-now",{method:"POST"});
  setTimeout(()=>{b.disabled=false;b.textContent="▶ Run now";refreshSched();},1500);
};
loadFields();refreshSched();setInterval(refreshSched,10000);
</script></body></html>"""
)
