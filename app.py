"""Navidromster — a Hitster-style music quiz on top of Navidrome. Stdlib only, no pip installs.

Run:
    NAVIDROME_URL=http://localhost:4533 NAVIDROME_USER=alice NAVIDROME_PASSWORD=secret python3 app.py

Then open http://<this-machine>:8000/cards, pick a playlist, print duplex,
cut the cards, and let players scan the QR codes.

Env:
    PORT            listen port (default 8000)
    NAVIDROMSTER_FORMAT  Navidrome stream format (default mp3; "raw" = original files)
    NAVIDROMSTER_INSECURE  set to 1 to skip SSL certificate verification (self-signed certs)
    PLAYER_URL      public base URL used in QR codes (default: address in the browser bar)
    NAVIDROMSTER_USER / NAVIDROMSTER_PASSWORD  login for the cards page and its API (unset = open)
"""

import hashlib
import hmac
import json
import logging
import os
import shutil
import ssl
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NAVIDROME_URL = os.environ.get("NAVIDROME_URL", "http://localhost:4533").rstrip("/")
NAVIDROME_USER = os.environ.get("NAVIDROME_USER", "")
NAVIDROME_PASSWORD = os.environ.get("NAVIDROME_PASSWORD", "")
STREAM_FORMAT = os.environ.get("NAVIDROMSTER_FORMAT", "mp3")
PLAYER_URL = os.environ.get("PLAYER_URL", "").rstrip("/")
APP_USER = os.environ.get("NAVIDROMSTER_USER", "")
APP_PASSWORD = os.environ.get("NAVIDROMSTER_PASSWORD", "")
PORT = int(os.environ.get("PORT", "8000"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("navidromster")

SSL_CONTEXT = ssl._create_unverified_context() if os.environ.get("NAVIDROMSTER_INSECURE") else None

AUTH_PARAMS = {"u": NAVIDROME_USER, "p": "enc:" + NAVIDROME_PASSWORD.encode().hex()}

SESSION_COOKIE = "navidromster_session"
SESSION_TOKEN = hashlib.sha256(f"{APP_USER}:{APP_PASSWORD}".encode()).hexdigest()[:32] if (APP_USER and APP_PASSWORD) else ""

LOGIN_HTML = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Navidromster login</title>
<style>
  body{margin:0;height:100vh;display:grid;place-items:center;background:#16161e;font-family:sans-serif;color:#eee}
  form{display:flex;flex-direction:column;gap:1rem;width:16rem}
  input,button{padding:.7rem;font-size:1rem;border-radius:.4rem;border:1px solid #444}
  input{background:#23232e;color:#eee}
  button{background:#e91e63;color:#fff;border:none;cursor:pointer}
  #err{color:#f66;font-weight:600;min-height:1.2em}
</style>
<form method="post" action="/login">
  <h2>&#127925; Navidromster</h2>
  <div id="err">__ERROR__</div>
  <input name="u" placeholder="Username" autocomplete="username" required autofocus>
  <input name="p" type="password" placeholder="Password" autocomplete="current-password" required>
  <button>Log in</button>
</form>
"""

PLAYER_HTML = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>&#127925;</title>
<style>
  body{margin:0;height:100vh;display:grid;place-items:center;background:#16161e;font-family:sans-serif}
  body.playing{animation:disco 5s linear infinite}
  @keyframes disco{0%{background:#16161e}20%{background:#3b0764}40%{background:#7c2d12}
                   60%{background:#134e4a}80%{background:#4a044e}100%{background:#16161e}}
  button{width:70vmin;height:70vmin;max-width:20rem;max-height:20rem;border-radius:50%;border:none;
         font-size:4rem;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;
         background:radial-gradient(circle,#e91e63 0 24%,transparent 25%),
                    repeating-radial-gradient(circle,#151515 0 2px,#232323 2px 4px);
         box-shadow:0 0 40px rgba(0,0,0,.8)}
  #i.play{width:0;height:0;margin-left:1.2rem;border-left:4rem solid #fff;
          border-top:2.3rem solid transparent;border-bottom:2.3rem solid transparent}
  #i.pause{width:2rem;height:4.4rem;border-left:1.2rem solid #fff;border-right:1.2rem solid #fff}
  #confetti{position:fixed;inset:0;pointer-events:none;overflow:hidden}
  #confetti i{position:absolute;top:-4vh;width:1rem;height:1.5rem;opacity:.9}
  body.playing #confetti i{animation:fall linear infinite}
  @keyframes fall{to{transform:translateY(115vh) rotate(720deg)}}
  body.playing button{animation:spin 3s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  body.playing::after{content:'🎵  🎶  🎵';position:fixed;bottom:8vh;left:0;right:0;
                      text-align:center;font-size:3rem;animation:bounce 1s ease-in-out infinite alternate}
  @keyframes bounce{to{transform:translateY(-4vh) scale(1.15)}}
</style>
<button id="b"><span id="i" class="play"></span></button>
<p id="m" style="color:#888;position:fixed;bottom:2rem;left:0;right:0;text-align:center"></p>
<audio id="a" preload="auto"></audio>
<script>
  const id = new URLSearchParams(location.search).get('s');
  const a = document.getElementById('a'), b = document.getElementById('b'),
        m = document.getElementById('m'), i = document.getElementById('i');
  if (!id) {
    b.style.display = 'none';
    m.textContent = 'No song here — scan a card QR code.';
  } else {
    a.src = '/stream?s=' + encodeURIComponent(id);
    a.onerror = () => { b.textContent = '❌'; b.disabled = true; m.textContent = 'Song unavailable.'; };
    b.onclick = () => a.paused ? a.play() : a.pause();
    a.onplay = () => { i.className = 'pause'; document.body.classList.add('playing'); };
    a.onpause = () => { i.className = 'play'; document.body.classList.remove('playing'); };
    a.play().catch(() => {});
  }

  const conf = document.createElement('div');
  conf.id = 'confetti';
  for (let n = 0; n < 50; n++) {
    const c = document.createElement('i');
    c.style.cssText = 'left:' + Math.random() * 100 + '%;background:hsl(' +
      Math.random() * 360 + ',90%,60%);animation-delay:-' + Math.random() * 5 +
      's;animation-duration:' + (3 + Math.random() * 3) + 's';
    conf.appendChild(c);
  }
  document.body.appendChild(conf);
</script>
"""

CARDS_HTML = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Navidromster card generator</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
<script>window.PLAYER_URL = __PLAYER_URL__;</script>
<style>
  body{font-family:sans-serif;margin:1rem}
  .controls{display:flex;gap:1rem;align-items:end;flex-wrap:wrap;margin-bottom:.5rem}
  label{display:flex;flex-direction:column;font-size:.85rem}
  .hint{font-size:.8rem;color:#a33;max-width:60rem}
  .page{width:210mm;height:297mm;box-sizing:border-box;padding:10mm;display:grid}
  input[type=file]{font-size:.75rem;max-width:11rem}
  img.art{max-height:22%;max-width:100%;object-fit:contain}
  .qrbox{flex:1;min-height:0;width:100%;display:flex;align-items:center;justify-content:center}
  .qrbox img,.qrbox canvas{max-width:100%;max-height:100%;width:auto;height:auto}
  .info{flex:1;min-height:0;display:flex;flex-direction:column;justify-content:center;overflow:hidden}
  .cell{border:1px dashed #bbb;display:flex;flex-direction:column;align-items:center;
        justify-content:center;text-align:center;overflow:hidden;padding:3mm}
  .back .cell{border:1px solid #000}
  .year{font-size:1.9em;font-weight:800}
  .artist{font-weight:700;margin-top:.8em}
  .title{margin-top:.25em}
  @media screen{.page{border:1px solid #ccc;margin:0 auto 1rem}}
  @media print{
    .controls,.hint{display:none}
    @page{size:A4;margin:0}
    .page{page-break-after:always;margin:0}
    .page:last-child{page-break-after:auto}
  }
</style>
<div class="controls">
  <label>Playlist <select id="pl"></select></label>
  <label>Columns <input id="cols" type="number" value="3" min="1" max="6"></label>
  <label>Rows <input id="rows" type="number" value="4" min="1" max="8"></label>
  <label>Duplex flip
    <select id="flip">
      <option value="long">Long edge (default)</option>
      <option value="short">Short edge</option>
    </select>
  </label>
  <label>Player base URL <input id="base" type="text" placeholder="(current address)" style="width:13rem"></label>
  <label>QR header <input type="file" accept="image/*" data-k="frontHead"></label>
  <label>QR footer <input type="file" accept="image/*" data-k="frontFoot"></label>
  <label>Answer header <input type="file" accept="image/*" data-k="backHead"></label>
  <label>Answer footer <input type="file" accept="image/*" data-k="backFoot"></label>
  <button onclick="gen()">Generate</button>
  <button onclick="print()">Print</button>
</div>
<p id="err" style="color:#c00;font-weight:600"></p>
<p class="hint">Set the Player base URL to the address phones will use (e.g. http://192.168.x.x:8000)
&mdash; defaults to the PLAYER_URL env var if set, else the current page address. Print double-sided, actual size (100% scale), matching
the flip mode above. Header/footer images are placed inside every card; on short-edge flip the
answer side swaps them automatically.</p>
<div id="out"></div>
<script>
const $ = s => document.querySelector(s);
const err = m => { $('#err').textContent = m || ''; };

const imgs = {};
document.querySelectorAll('input[type=file]').forEach(i => i.onchange = () => {
  const f = i.files[0];
  if (!f) { imgs[i.dataset.k] = null; return; }
  const r = new FileReader();
  r.onload = () => { imgs[i.dataset.k] = r.result; };
  r.readAsDataURL(f);
});

$('#base').value = localStorage.navidromsterBase || window.PLAYER_URL || '';
$('#base').onchange = e => { localStorage.navidromsterBase = e.target.value; };

async function get(url) {
  const r = await fetch(url);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || ('HTTP ' + r.status));
  return body;
}

get('/playlists').then(p => {
  if (!p.length) err('Server returned zero playlists (visible to this Navidrome user).');
  for (const x of p) {
    const o = document.createElement('option');
    o.value = x.id;
    o.textContent = x.name + ' (' + x.songCount + ')';
    $('#pl').appendChild(o);
  }
}).catch(e => err('Failed to load playlists: ' + e.message));

function art(url) {
  const i = document.createElement('img');
  i.className = 'art';
  i.src = url;
  return i;
}

function qrCell(s, base) {
  const c = document.createElement('div');
  c.className = 'cell';
  if (!s) return c;
  c.classList.add('qr');
  if (imgs.frontHead) c.appendChild(art(imgs.frontHead));
  const box = document.createElement('div');
  box.className = 'qrbox';
  new QRCode(box, {text: base + '/play?s=' + s.id, width: 256, height: 256,
                   correctLevel: QRCode.CorrectLevel.M});
  c.appendChild(box);
  if (imgs.frontFoot) c.appendChild(art(imgs.frontFoot));
  return c;
}

function infoCell(s, head, foot) {
  const c = document.createElement('div');
  c.className = 'cell';
  if (!s) return c;
  if (head) c.appendChild(art(head));
  const info = document.createElement('div');
  info.className = 'info';
  for (const [cls, val] of [['year', s.year], ['artist', s.artist], ['title', s.title]]) {
    const d = document.createElement('div');
    d.className = cls;
    d.textContent = val;
    info.appendChild(d);
  }
  c.appendChild(info);
  if (foot) c.appendChild(art(foot));
  return c;
}

function page(cols, rows, cls) {
  const p = document.createElement('div');
  p.className = 'page ' + cls;
  p.style.gridTemplate = 'repeat(' + rows + ',1fr)/repeat(' + cols + ',1fr)';
  return p;
}

async function gen() {
  err('');
  if (!$('#pl').value) { err('Pick a playlist first.'); return; }
  const cols = +$('#cols').value, rows = +$('#rows').value, flip = $('#flip').value;
  const songs = await get('/playlist?id=' + encodeURIComponent($('#pl').value))
    .catch(e => { err('Failed to load playlist: ' + e.message); return null; });
  if (!songs) return;
  if (!songs.length) { err('Playlist is empty.'); return; }
  const base = ($('#base').value.trim() || location.origin).replace(/[/]+$/, '');
  const [backHead, backFoot] = flip === 'short' ? [imgs.backFoot, imgs.backHead] : [imgs.backHead, imgs.backFoot];
  const out = $('#out');
  out.innerHTML = '';
  for (let i = 0; i < songs.length; i += cols * rows) {
    const padded = songs.slice(i, i + cols * rows);
    while (padded.length < cols * rows) padded.push(null);
    const front = page(cols, rows, 'front');
    for (const s of padded) front.appendChild(qrCell(s, base));
    const grid = [];
    for (let r = 0; r < rows; r++) grid.push(padded.slice(r * cols, (r + 1) * cols));
    const ordered = flip === 'long' ? grid.map(r => [...r].reverse()) : [...grid].reverse();
    const back = page(cols, rows, 'back');
    for (const row of ordered) for (const s of row) back.appendChild(infoCell(s, backHead, backFoot));
    out.append(front, back);
  }
}
</script>
"""


def navidrome(endpoint, **params):
    query = {**AUTH_PARAMS, "v": "1.16.1", "c": "navidromster", **params}
    return urllib.request.Request(
        f"{NAVIDROME_URL}/rest/{endpoint}?{urllib.parse.urlencode(query)}",
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"})


def navidrome_json(endpoint, **params):
    log.info("navidrome: %s %s", endpoint, params)
    with urllib.request.urlopen(navidrome(endpoint, f="json", **params), context=SSL_CONTEXT) as r:
        data = json.load(r)["subsonic-response"]
    if data.get("status") != "ok":
        log.error("navidrome: %s failed: %s", endpoint, data)
        raise RuntimeError(data)
    return data


def make_handler():
    class Handler(BaseHTTPRequestHandler):
        def send_body(self, body, content_type, status=200):
            raw = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def authorized(self, wants_json):
            if not SESSION_TOKEN:
                return True
            cookies = urllib.parse.parse_qsl(
                self.headers.get("Cookie", "").replace("; ", "&"))
            token = dict(cookies).get(SESSION_COOKIE, "")
            if hmac.compare_digest(token, SESSION_TOKEN):
                return True
            if wants_json:
                self.send_body(json.dumps({"error": "Not logged in"}),
                               "application/json", status=401)
            else:
                self.send_response(303)
                self.send_header("Location", "/login")
                self.send_header("Content-Length", "0")
                self.end_headers()
            return False

        def do_POST(self):
            url = urllib.parse.urlparse(self.path)
            if url.path != "/login":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode()))
            if hmac.compare_digest(form.get("u", ""), APP_USER) and \
               hmac.compare_digest(form.get("p", ""), APP_PASSWORD):
                self.send_response(303)
                self.send_header("Set-Cookie",
                                 f"{SESSION_COOKIE}={SESSION_TOKEN}; HttpOnly; SameSite=Lax; Path=/")
                self.send_header("Location", "/cards")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                log.warning("login failed for user %r", form.get("u", ""))
                self.send_body(LOGIN_HTML.replace("__ERROR__", "Wrong username or password."),
                               "text/html; charset=utf-8", status=401)

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path == "/login":
                self.send_body(LOGIN_HTML.replace("__ERROR__", ""), "text/html; charset=utf-8")
                return
            if url.path in ("/", "/cards", "/playlists", "/playlist"):
                if not self.authorized(url.path.startswith("/playlist")):
                    return
            q = urllib.parse.parse_qs(url.query)
            try:
                if url.path in ("/", "/cards"):
                    self.send_body(CARDS_HTML.replace("__PLAYER_URL__", json.dumps(PLAYER_URL)),
                                   "text/html; charset=utf-8")
                elif url.path == "/play":
                    self.send_body(PLAYER_HTML, "text/html; charset=utf-8")
                elif url.path == "/playlists":
                    pls = navidrome_json("getPlaylists").get("playlists", {}).get("playlist", [])
                    self.send_body(json.dumps([
                        {"id": p["id"], "name": p["name"], "songCount": p.get("songCount", 0)}
                        for p in pls
                    ]), "application/json")
                elif url.path == "/playlist":
                    pl = navidrome_json("getPlaylist", id=q["id"][0]).get("playlist", {})
                    self.send_body(json.dumps([
                        {"id": s["id"], "artist": s.get("artist", "?"),
                         "title": s.get("title", "?"), "year": s.get("year", "?")}
                        for s in pl.get("entry", [])
                    ]), "application/json")
                elif url.path == "/stream":
                    self.stream(q["s"][0])
                else:
                    self.send_error(404)
            except urllib.error.HTTPError as e:
                snippet = e.read(300).decode("utf-8", "replace")
                log.error("navidrome HTTP %s for %s — body starts: %s", e.code, self.path, snippet)
                self.send_body(json.dumps({"error": f"Navidrome answered HTTP {e.code}"}),
                               "application/json", status=502)
            except Exception as e:
                log.exception("request failed: %s", self.path)
                self.send_body(json.dumps({"error": str(e)}), "application/json", status=502)

        def stream(self, song_id):
            log.info("stream: song %s", song_id)
            req = navidrome("stream", id=song_id, format=STREAM_FORMAT)
            if self.headers.get("Range"):
                req.add_header("Range", self.headers["Range"])
            with urllib.request.urlopen(req, context=SSL_CONTEXT) as r:
                self.send_response(r.status)
                for h in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                    v = r.headers.get(h)
                    if v:
                        self.send_header(h, v)
                self.end_headers()
                shutil.copyfileobj(r, self.wfile)

        def log_message(self, fmt, *args):
            log.info("http: " + fmt, *args)

    return Handler


def main():
    log.info("navidrome server: %s (user=%s)", NAVIDROME_URL, NAVIDROME_USER or "(unset!)")
    if SSL_CONTEXT:
        log.warning("SSL certificate verification DISABLED (NAVIDROMSTER_INSECURE is set)")
    log.info("navidromster on http://0.0.0.0:%s — cards: /cards, player: /play", PORT)
    log.info("cards page: %s", "login ON" if SESSION_TOKEN
             else "OPEN — set NAVIDROMSTER_USER/NAVIDROMSTER_PASSWORD to protect")
    ThreadingHTTPServer(("0.0.0.0", PORT), make_handler()).serve_forever()


if __name__ == "__main__":
    main()
