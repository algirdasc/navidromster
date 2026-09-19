"""Smoke test: stubs Navidrome, verifies proxying, auth params, and Range passthrough."""

import base64
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class StubNavidrome(BaseHTTPRequestHandler):
    def do_POST(self):
        assert urllib.parse.urlparse(self.path).path == "/auth/login", self.path
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body == {"username": "u", "password": "p"}, body
        self._json({"token": "tok"})

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        assert "Mozilla" in self.headers.get("User-Agent", ""), "missing browser User-Agent"
        if url.path.startswith("/rest/"):
            assert {"u", "p"} <= set(q) and q["p"][0].startswith("enc:"), "missing Subsonic auth params"
        if url.path == "/api/playlist/pl1/tracks":
            assert self.headers.get("X-ND-Authorization") == "Bearer tok"
            self._json([
                {"id": "s1", "artist": "ABBA", "title": "Waterloo", "year": 1974},
                {"id": "s2", "artist": "ABBA", "title": "Waterloo (Remaster)",
                 "year": 2001, "date": "2001-05-06", "originalDate": "1974-03-04"},
                {"id": "s3", "artist": "ABBA", "title": "Untagged", "year": 0, "albumId": "a1"}])
        elif url.path == "/rest/getAlbum":
            self._json({"subsonic-response": {"status": "ok", "album": {
                "id": "a1", "originalReleaseDate": {"year": 1973, "month": 7, "day": 6}}}})
        elif url.path == "/rest/getPlaylists":
            self._json({"subsonic-response": {"status": "ok", "playlists": {"playlist": [
                {"id": "pl1", "name": "Party", "songCount": 1}]}}})
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
        token = base64.b64encode(b"cu:cp").decode()
        req = urllib.request.Request(base + path, headers={"Authorization": "Basic " + token})
        return urllib.request.urlopen(req)

    for path in ("/cards", "/playlists", "/playlist?id=pl1"):
        try:
            urllib.request.urlopen(base + path)
            raise AssertionError(path + " should require auth")
        except urllib.error.HTTPError as e:
            assert e.code == 401, (path, e.code)

    pls = json.load(authed("/playlists"))
    assert pls == [{"id": "pl1", "name": "Party", "songCount": 1}], pls

    songs = json.load(authed("/playlist?id=pl1"))
    assert songs == [{"id": "s1", "artist": "ABBA", "title": "Waterloo", "year": 1974},
                     {"id": "s2", "artist": "ABBA", "title": "Waterloo (Remaster)", "year": "1974-03-04"},
                     {"id": "s3", "artist": "ABBA", "title": "Untagged", "year": "1973-07-06"}], songs

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
