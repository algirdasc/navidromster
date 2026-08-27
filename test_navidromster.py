"""Smoke test: stubs Navidrome, verifies proxying, auth params, and Range passthrough."""

import hashlib
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class StubNavidrome(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        assert {"u", "p"} <= set(q) and q["p"][0].startswith("enc:"), "missing Subsonic auth params"
        assert "Mozilla" in self.headers.get("User-Agent", ""), "missing browser User-Agent"
        if url.path == "/rest/getPlaylists":
            self._json({"subsonic-response": {"status": "ok", "playlists": {"playlist": [
                {"id": "pl1", "name": "Party", "songCount": 1}]}}})
        elif url.path == "/rest/getPlaylist":
            self._json({"subsonic-response": {"status": "ok", "playlist": {"entry": [
                {"id": "s1", "artist": "ABBA", "title": "Waterloo", "year": 1974}]}}})
        elif url.path == "/rest/stream":
            if q["id"][0] != "s1":
                self.send_error(404)
                return
            if self.headers.get("Range"):
                self.send_response(206)
                self.send_header("Content-Range", "bytes 0-9/100")
                self.send_header("Content-Type", "audio/mpeg")
                self.end_headers()
                self.wfile.write(b"0123456789")
            else:
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.end_headers()
                self.wfile.write(b"X" * 100)

    def _json(self, obj):
        raw = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


def main():
    stub = ThreadingHTTPServer(("127.0.0.1", 0), StubNavidrome)
    threading.Thread(target=stub.serve_forever, daemon=True).start()

    os.environ["NAVIDROME_URL"] = f"http://127.0.0.1:{stub.server_address[1]}"
    os.environ["NAVIDROME_USER"] = "u"
    os.environ["NAVIDROME_PASSWORD"] = "p"
    os.environ["NAVIDROMSTER_USER"] = "cu"
    os.environ["NAVIDROMSTER_PASSWORD"] = "cp"

    import app
    server = ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def authed(path):
        req = urllib.request.Request(base + path, headers={"Cookie": cookie})
        return urllib.request.urlopen(req)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a):
            return None

    no_redirect = urllib.request.build_opener(NoRedirect)

    login = urllib.request.Request(base + "/login",
                                   data=urllib.parse.urlencode({"u": "cu", "p": "cp"}).encode())
    try:
        no_redirect.open(login)
        raise AssertionError("login should redirect")
    except urllib.error.HTTPError as e:
        assert e.code == 303, e.code
        cookie = e.headers["Set-Cookie"].split(";")[0]
        assert cookie == "navidromster_session=" + hashlib.sha256(b"cu:cp").hexdigest()[:32]

    bad_login = urllib.request.Request(base + "/login",
                                       data=urllib.parse.urlencode({"u": "cu", "p": "wrong"}).encode())
    try:
        no_redirect.open(bad_login)
        raise AssertionError("bad login should fail")
    except urllib.error.HTTPError as e:
        assert e.code == 401, e.code

    try:
        no_redirect.open(base + "/cards")
        raise AssertionError("/cards should redirect to /login")
    except urllib.error.HTTPError as e:
        assert e.code == 303 and e.headers["Location"] == "/login", (e.code, e.headers.get("Location"))

    for path in ("/playlists", "/playlist?id=pl1"):
        try:
            urllib.request.urlopen(base + path)
            raise AssertionError(path + " should require login")
        except urllib.error.HTTPError as e:
            assert e.code == 401, (path, e.code)

    pls = json.load(authed("/playlists"))
    assert pls == [{"id": "pl1", "name": "Party", "songCount": 1}], pls

    songs = json.load(authed("/playlist?id=pl1"))
    assert songs == [{"id": "s1", "artist": "ABBA", "title": "Waterloo", "year": 1974}], songs

    assert urllib.request.urlopen(base + "/stream?s=s1").read() == b"X" * 100

    req = urllib.request.Request(base + "/stream?s=s1", headers={"Range": "bytes=0-9"})
    with urllib.request.urlopen(req) as r:
        assert r.status == 206, r.status
        assert r.headers["Content-Range"] == "bytes 0-9/100"
        assert r.read() == b"0123456789"

    try:
        urllib.request.urlopen(base + "/stream?s=deleted")
        raise AssertionError("dead song should fail")
    except urllib.error.HTTPError as e:
        assert e.code == 502, e.code

    html = urllib.request.urlopen(base + "/play").read().decode()
    assert "<audio" in html and "Waterloo" not in html

    assert authed("/cards").read()

    print("ok")


if __name__ == "__main__":
    main()
