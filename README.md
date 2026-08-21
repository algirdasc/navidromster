# Navidromster

A Hitster-style music guessing game on top of your [Navidrome](https://www.navidrome.org/) server.
Print cards with QR codes; players scan them to hear the song — title, artist and year stay hidden
on the card back and out of the player.

- **Card generator** (`/cards`) — pick a Navidrome playlist, get an A4 duplex-printable sheet:
  QR codes on the front, year/artist/title on the back, mirrored for your printer's flip mode.
  Optional header/footer artwork per card side, optional basic auth.
- **Player** (`/play?s=<id>`) — one big vinyl play/pause button, autoplay attempt, disco mode
  while playing, zero metadata leaks (page title, URL and markup are all clean).

Single Python file, standard library only. No pip install, no build step.

## Requirements

- A Navidrome server
- Python 3.8+ *or* Docker
- Internet access on the machine generating cards (QR library loads from CDN)

## Run

Bare Python:

```bash
NAVIDROME_URL=https://music.example.com \
NAVIDROME_USER=alice \
NAVIDROME_PASSWORD='secret' \
python3 app.py
```

Docker (compose pulls the pre-built GHCR image published on every release):

```bash
cp .env.example .env   # fill in your values
docker compose up -d
```

Without compose:

```bash
docker run -d -p 8000:8000 --env-file .env ghcr.io/algirdasc/navidromster:latest
```

Then open `http://<host>:8000/cards`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `NAVIDROME_URL` | `http://localhost:4533` | Your Navidrome server |
| `NAVIDROME_USER` / `NAVIDROME_PASSWORD` | — | Navidrome account for playlists + streaming. Single-quote the password if it contains `$`, `!` or spaces |
| `PORT` | `8000` | Listen port |
| `PLAYER_URL` | address in browser | Public base URL baked into QR codes — set when behind a reverse proxy |
| `NAVIDROMSTER_USER` / `NAVIDROMSTER_PASSWORD` | unset | Basic auth for the cards page and its API. Both set = on |
| `NAVIDROMSTER_FORMAT` | `mp3` | Navidrome stream format (`raw` = no transcoding) |
| `NAVIDROMSTER_INSECURE` | unset | `1` skips SSL certificate verification (self-signed certs) |

## Printing cards

1. Open `/cards` via the address phones will use (or set `PLAYER_URL`) — QR codes embed it.
2. Pick a playlist, grid size and your printer's duplex flip mode (long edge is the default).
3. Print double-sided at 100% scale, cut along the dashed lines.

## Test

```bash
python3 test_navidromster.py
```

Stubs a Navidrome server and checks auth params, playlist proxying, Range-request passthrough
and the basic-auth gate.

## Notes

- iOS Safari/Chrome block autoplay with sound — players tap the vinyl once, then it spins.
- Streaming is anonymous by design (it's a party game); the cards page is what basic auth protects.
