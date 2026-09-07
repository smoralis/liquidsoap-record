# Liquidsoap Record

A tool for recording internet radio streams (Shoutcast/Icecast/HTTP streams)
to disk with automatic track-splitting, ID3/Vorbis metadata tagging, and
cover-art embedding — driven by [Liquidsoap](https://www.liquidsoap.info/)
and controlled through a desktop GUI (with an optional web interface).

The project has three parts:

| File | Role |
|---|---|
| `record.liq` | The Liquidsoap script that does the actual stream capture, file writing, metadata handling, and post-processing. |
| `liquidsoap-record-ui.py` | A Tkinter desktop application that builds the command line for `record.liq`, launches/monitors it as a subprocess, and optionally exposes the same controls over a small built-in web server. |
| `build_cover_metadata.py` | A helper invoked by `record.liq` to embed cover art in Ogg Vorbis / Opus files (a format that ffmpeg's normal `attached_pic` shortcut doesn't support). |

## How it fits together

1. You configure a stream URL, output directory, format/codec, and various
   options either in the GUI or on the liquidsoap command line.
2. The GUI (`liquidsoap-record-ui.py`) assembles these into a
   `liquidsoap record.liq -- -url ... -dir ... ...` command and runs it as a
   subprocess, streaming its log output back into the GUI/web log panel.
3. `record.liq` connects to the stream (via `input.ffmpeg`), writes audio to
   disk, and either:
   - **copies** the source stream as-is ("stream copy" mode), or
   - **transcodes** it to a chosen format/codec/bitrate/samplerate.
4. Track metadata (ICY `artist`/`title`, or a combined `title` string) is
   parsed, cleaned, and used to split the recording into per-track files
   (unless "single" mode is enabled, in which case it records one continuous
   file).
5. When a new track starts, `record.liq` can optionally look up cover art
   (from a metadata URL, TuneIn, or Deezer) and embed it into the finished
   file with `ffmpeg` once the track is complete — using
   `build_cover_metadata.py` for the Ogg/Opus cases.
6. Liquidsoap also exposes a tiny HTTP control server (`harbor.http`) on
   `127.0.0.1:1234` with a `/stop_all` endpoint the GUI uses to shut it down
   gracefully.

## `record.liq`

Liquidsoap script (targets Liquidsoap 2.4.5) invoked as:

```
liquidsoap record.liq -- \
  -url "<stream url>" \
  -dir "<output directory>" \
  -station "<station name>" \
  -transcode <0|1> \
  -samplerate "<samplerate>" \
  -format "<mp3|m4a|flac|ogg|opus>" \
  -codec "<libmp3lame|aac|flac|libopus|vorbis>" \
  -bitrate "<bitrate>" \
  -listen <0|1> \
  -device "<portaudio|alsa>" \
  -log <1-4> \
  -keep <0|1> \
  -id "<tunein id>" \
  -relay <0|1> \
  -host "<icecast relay host>" \
  -port <icecast relay port> \
  -password "<icecast relay password>" \
  -m3u <0|1> \
  -covers <0|1> \
  -single <0|1> \
  -timeout <seconds, 0 = unlimited>
```

Key behavior:

- **Folder naming** — uses the station name if given, otherwise probes the
  stream's ICY `icy-name` with `ffprobe`, otherwise falls back to a
  sanitized version of the URL.
- **Stream copy vs. transcode** — if `-transcode 0`, `ffprobe` is used to
  detect the source codec and the stream is copied through without
  re-encoding; if `-transcode 1`, audio is re-encoded to the requested
  format/codec/bitrate/samplerate.
- **Metadata cleanup** — normalizes uppercase `ARTIST`/`TITLE` tags, and
  splits combined `"Artist - Title"` (or `Artist ? Title`) strings into
  separate artist/title fields, stripping trailing `[...]`/`|...` junk.
- **Track splitting** — `reopen_on_metadata` reopens the output file
  whenever the artist/title changes, naming each file after the sanitized
  artist/title (or just title, or a timestamp if no metadata is available).
  Disabled entirely in `-single 1` mode.
- **Cover art** — when `-covers 1`, on each new track it tries, in order: a
  cover URL embedded in the stream's metadata, a TuneIn "now playing" image
  (if `-id` is set), or a Deezer search by artist/title. The image is
  downloaded, then muxed into the finished file with `ffmpeg` once the file
  closes (FLAC/MP3/M4A use `-disposition:v attached_pic`; Ogg/Opus use
  `build_cover_metadata.py` to build a proper `METADATA_BLOCK_PICTURE` tag).
  If muxing fails for any reason, the original (uncovered) recording is kept
  rather than lost.
- **M3U** — when `-m3u 1`, writes a `#listen.m3u` playlist file pointing at
  the source URL into the output folder.
- **Icecast relay** — when `-relay 1`, additionally re-streams the audio out
  to an Icecast server (AAC/ADTS, 320k) at the given host/port/password, and
  can push live artist/title/cover-url ICY metadata updates to it.
- **Listening** — when `-listen 1`, plays the audio live through
  `output.portaudio` or `output.alsa` (whichever is compiled in).
- **Timeout / watchdog** — a background thread checks elapsed recording time
  every second and calls `shutdown()` once `-timeout` (seconds) is reached.
- **Control endpoint** — `harbor.http` listens on `127.0.0.1:1234` and
  exposes `GET /stop_all`, which calls `shutdown()`.
  
## Examples

Stream Copy
```
liquidsoap record.liq -- -url "http://ice1.somafm.com/groovesalad-256-mp3" -dir "c:\music"
```

Transcoding
```
liquidsoap record.liq -- -url "https://stream.radioparadise.com/rock-flacm" -dir "c:\music" -transcode 1 -samplerate 48000 -format opus -codec libopus -bitrate 128k

```

Stream Copy with tunein_id (e.g) https://tunein.com/radio/Roxx-Radio-s240638/
```
liquidsoap record.liq -- -url "http://stream.radiojar.com/aay95tkmb" -dir "c:\music" -covers 1 -id s240638
```

## Transcoding

Transcoding suggestions table

| format     | arguments|
| ------------- | ------------- |
| OPUS          | -samplerate 48000 -format opus -codec libopus -bitrate 128k|
| MP3         | -samplerate 44100 -format mp3 -codec libmp3lame -bitrate 320k |
| AAC        | -samplerate 44100 -format mp4 -codec aac -bitrate 320k|
| FLAC        | -samplerate 44100 -format flac -codec flac|


## `liquidsoap-record-ui.py`

A single-file Tkinter application (Linux/Windows/macOS) that wraps
`record.liq`:

- **Recorder tab** — start/stop controls, live status, elapsed time, current
  file being recorded, a log panel, and a built-in Icecast relay player
  (via `mpv` or `ffplay`, with a volume slider) for monitoring the relay
  output.
- **Options tab** — every `record.liq` flag exposed as a form field (stream
  URL, directory, station, transcode/codec/format/bitrate/samplerate,
  listen device, log level, keep-incomplete, timeout, TuneIn ID, M3U,
  covers, single-track mode, Icecast relay host/port/password) plus web
  interface settings.
- **Files tab** — a browsable tree of the recording output directory, with
  "open file" / "open containing folder" actions.
- Builds the actual `liquidsoap record.liq -- ...` command line from the
  form (`build_command`), can show/copy it, and launches it as a subprocess,
  parsing its stdout/stderr into the log panel and status fields in real
  time.
- Stops recording gracefully by calling the `/stop_all` HTTP endpoint first
  (falling back to killing the process if it doesn't exit in time).
- Persists all settings between runs to
  `~/.liquidsoap_record_parameters.json`; explicit command-line arguments to
  the GUI itself always override saved values.
- Detects and displays the installed Liquidsoap version and the
  `record.liq` script version (parsed from its header comment).
- **Optional web interface** — an embedded `ThreadingHTTPServer` (off by
  default, toggle in Options) serves a single-page control UI plus a small
  JSON API (`GET /api/status`, `/api/parameters`, `/api/log`;
  `POST /api/start`, `/api/stop`, `/api/parameters`) so the recorder can be
  started/stopped/monitored remotely, e.g. from a phone browser.
- Supports light/dark themes (persisted) and can be launched with
  `--start-recording` to begin recording immediately on startup.

Run it with `python3 liquidsoap-record-ui.py [options]` — see
`parse_arguments()` in the script (or `--help`) for the full list of
command-line overrides, which mirror the `record.liq` flags above plus
`--web`, `--web-host`, and `--web-port`.

## `build_cover_metadata.py`

```
build_cover_metadata.py <cover_image> <output_metadata_file>
```

A standalone helper called by `record.liq`'s post-processing step for Ogg
Vorbis and Opus output. ffmpeg's `-disposition:v attached_pic` shortcut
(used for FLAC/MP3/M4A) doesn't produce a valid cover tag for Ogg-family
containers, so this script builds the required `METADATA_BLOCK_PICTURE`
value by hand, per the
[Xiph FLAC picture block spec](https://xiph.org/flac/format.html#metadata_block_picture):

1. Guesses the image's MIME type from its file extension and probes its
   pixel dimensions with `ffprobe`.
2. Packs the FLAC `PICTURE` metadata block (type = front cover, MIME type,
   empty description, width/height/depth/colors, and the raw image bytes)
   and base64-encodes it.
3. Writes it out as an `;FFMETADATA1` file containing a single
   `METADATA_BLOCK_PICTURE=<base64>` line.

`record.liq` then feeds that file back into ffmpeg with
`-i metadata.txt -map_metadata 1`, avoiding the need to pass a large base64
blob as a command-line argument. On any failure it exits non-zero and
writes nothing to the output file, so the caller can detect the failure and
keep the original (uncovered) recording instead of losing it.

## Requirements

- [Liquidsoap](https://www.liquidsoap.info/) 2.4.5 (built with
  `output.portaudio`/`output.alsa` support if you want live listening)
- `ffmpeg` / `ffprobe`
- Python 3 (for the GUI and `build_cover_metadata.py`); Tkinter for the GUI
- `mpv` or `ffplay` (optional, for the built-in Icecast relay player)