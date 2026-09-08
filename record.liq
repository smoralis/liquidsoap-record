#record.liq
#Version 1.0.51 2026-09-08
#Liquidsoap 2.4.5

#usage liquidsoap record.liq -- -url "<url>" -dir "<directory>" -station "<station>" -transcode <0> -samplerate "<samplerate>" -format "<format>" -codec "<codec>" -bitrate "<bitrate>" -listen <0> -device "<portaudio><alsa>" -log <2> -keep <0> -id <tunein_id> -relay <0> -host "<host>" -port <port> -password "<password>" -m3u <0> -covers <0> -single <0> -timeout <0>

# ------------------------------------------------------------
# REFERENCES / DEFINITIONS
# ------------------------------------------------------------

urlx = ref("")
ext = ref("")
cformat = ref("")
codec_name = ref("")
urlx.set(getopt(default="https://example.com","-url"))
directory = getopt(default="/Directory","-dir")
station = ref("")
station.set(getopt(default="This station","-station"))
folder = ref("")
transcode = getopt(default="0", "-transcode")
samplerate = getopt(default="44100", "-samplerate")
formatx = getopt(default="mp3", "-format")
codec = getopt(default="libmp3lame", "-codec")
bitrate = getopt(default="320k", "-bitrate")
listen = getopt(default="0", "-listen")
device = getopt(default="portaudio", "-device")
logoutput = getopt(default="2", "-log")
keep = getopt(default="0", "-keep")
timeout = ref("")
timeout.set(getopt(default="0", "-timeout"))
artist = ref("")
title = ref("")
tmp_artist = ref("")
tmp_title = ref("")
counter = ref(-1)
nowrecording = ref("")
cover = ref("")
tunein_id = ref("")
tunein_id.set(getopt(default=" ","-id"))
relay = getopt(default="0", "-relay")
hostx = getopt(default="localhost", "-host")
port = getopt(default="8000", "-port")
password = getopt(default="hackme", "-password")
m3u = getopt(default="0", "-m3u")
covers = getopt(default="0", "-covers")
singlex = getopt(default="0", "-single")

# ------------------------------------------------------------
# LOG HELPERS
# ------------------------------------------------------------

def log_level_1(msg) =
  log(label="liquidsoap-record", level=1, msg)
end

def log_level_2(msg) =
  log(label="liquidsoap-record", level=2, msg)
end

def log_level_3(msg) =
  log(label="liquidsoap-record", level=3, msg)
end

def log_level_4(msg) =
  log(label="liquidsoap-record", level=4, msg)
end


# ------------------------------------------------------------
#2.5.0 experimental Icecast server
# ------------------------------------------------------------

#DISABLED for 2.4.5
#<

if
  relay == "1" 
then
  icecast_server = icecast.server(port=8001, password="hackme")

  # React when a source connects
  icecast_server.on_connect(
    fun (r) ->
      log.important(
        "Source connected on mount #{r.mount}"
      )
  )

  # React when a source disconnects
  icecast_server.on_disconnect(
    fun (r) ->
      log.important(
        "Source disconnected from mount #{r.mount}"
      )
  )
end

>#


# ------------------------------------------------------------
# INITIAL SETUP
# ------------------------------------------------------------

file.mkdir(directory)

settings.encoder.metadata.export :=
  [
    "artist",
    "title",
    "album",
    "genre",
    "date",
    "tracknumber",
    "comment",
    "track",
    "year",
    "dj",
    "next",
    "apic",
    "pic",
    "metadata_url",
    "metadata_block_picture",
    "coverart",
    "cover_url",
    "url"
  ]

# ------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------
settings.log.level.set(int_of_string(logoutput))
settings.ffmpeg.log.verbosity := "error"

# ------------------------------------------------------------
# SCHEDULER
# ------------------------------------------------------------
settings.scheduler.generic_queues.set(1)
settings.scheduler.fast_queues.set(0)
settings.scheduler.non_blocking_queues.set(1)
settings.scheduler.log.set(true)

# ------------------------------------------------------------
# SET EXTENSION FROM SELECTED CODEC
# ------------------------------------------------------------

if codec == "libmp3lame" then ext.set("mp3") end

if codec == "aac" then ext.set("m4a") end

if codec == "flac" then ext.set("flac") end

if codec == "libopus" then ext.set("opus") end

if codec == "vorbis" then ext.set("ogg") end

# ------------------------------------------------------------
# REMOVE ILLEGAL FILENAME CHARACTERS
# ------------------------------------------------------------

def remove_illegal(value) =
  str = r/[\?\<\>]/g.replace(fun (_) -> "_", value)
  str = r/[\*<>]/g.replace(fun (_) -> "x", str)
  str = r/[\:\/|\\]/g.replace(fun (_) -> "-", str)
  str = r/[\"]/g.replace(fun (_) -> "''", str)
  str = r/[\.]/g.replace(fun (_) -> "", str)
  str
end

# ------------------------------------------------------------
# STRIP URL AFTER &
# ------------------------------------------------------------

def split_url() =
  if
    string.contains(substring="&", urlx())
  then
    let (u, r) = string.split.first(separator="&", urlx())
    urlx.set(u)

    log_level_2("Stripped %urlx% after & of: " ^
        r)
  end
end

split_url()

# ------------------------------------------------------------
# INITIAL FOLDER
# ------------------------------------------------------------

folder.set(string.trim(remove_illegal(urlx())))

# ------------------------------------------------------------
# FFPROBE ICY-NAME
# ------------------------------------------------------------

def ffprobe_name() =
  if
    station() !=
      " "
  then
    folder.set(string.trim(remove_illegal(station())))
  else
    icy_name =
      process.read(
        "ffprobe -v quiet -print_format json " ^
          "-select_streams a:0 " ^
          "-show_entries format=format_tags:format_tags=icy-name " ^
          "-of default=noprint_wrappers=1:nokey=1 " ^
          process.quote(urlx())
      )

    icy_name = r/(\r\n|\n|\r)/g.replace(fun (_) -> "", icy_name)

    log_level_2("FFPROBE icy-name: #{icy_name}")

    if icy_name != "" then folder.set(string.trim(remove_illegal(icy_name))) end
  end

  log_level_2("Saving to folder: " ^
      folder())
end

ffprobe_name()

# ------------------------------------------------------------
# FFPROBE SOURCE CODEC
# ------------------------------------------------------------

def ffprobe_url() =
  try
    j =
      process.read(
        "ffprobe -v quiet " ^
          "-print_format json " ^
          "-select_streams a:0 " ^
          "-show_entries stream=codec_name " ^
          "-of json=compact=1 " ^
          urlx()
      )

    let json.parse ({streams = [c1]} : {streams: [{codec_name: string}]}) = j

    codec_name.set(string(c1.codec_name))

    log_level_2("FFPROBE codec_name: " ^
        codec_name())

    if
      codec_name() == "mp3"
    then
      cformat.set("mp3")
      ext.set("mp3")
    end

    if
      codec_name() == "aac"
    then
      cformat.set("mp4")
      ext.set("m4a")
    end

    if
      codec_name() == "flac"
    then
      cformat.set("flac")
      ext.set("flac")
    end

    if
      codec_name() == "opus"
    then
      cformat.set("ogg")
      ext.set("opus")
    end

    if
      codec_name() == "vorbis"
    then
      cformat.set("ogg")
      ext.set("ogg")
    end
  catch err do
    log_level_2("ffprobe failed to get codec_name!!! with error: #{err.message}")

    log_level_2("Is the stream online ??")
  end
end

# Stream-copy mode:
# Detect source codec automatically.
if transcode == "0" then ffprobe_url() end

# ------------------------------------------------------------
# FORMAT TIME
# ------------------------------------------------------------

def format_time(timex) =
  seconds = int(timex mod 60.)

  seconds_string =
    if seconds < 10 then "0" ^ string(seconds) else string(seconds) end

  minutes = int(timex / 60.)

  minutes_string =
    if minutes < 10 then "0" ^ string(minutes) else string(minutes) end

  minutes_string ^ ":" ^ seconds_string
end

# ------------------------------------------------------------
# M3U PLAYLIST
# ------------------------------------------------------------

if
  m3u == "1"
then
  m3u = ref("#{directory}/" ^ folder())

  file.mkdir(m3u())

  file.write(data=urlx(), m3u() ^ "/#listen.m3u")
end

# ------------------------------------------------------------
# LOWERCASE ARTIST
# ------------------------------------------------------------

def lower_ARTIST(m) =
  if
    m["ARTIST"] != ""
  then
    [("artist", m["ARTIST"]), ("ARTIST", "")]
  else
    []
  end
end

# ------------------------------------------------------------
# LOWERCASE TITLE
# ------------------------------------------------------------

def lower_TITLE(m) =
  if m["TITLE"] != "" then [("title", m["TITLE"]), ("TITLE", "")] else [] end
end

# ------------------------------------------------------------
# CLEAN METADATA
# ------------------------------------------------------------

def clean_metadata(m) =
  m
end

# ------------------------------------------------------------
# SPLIT TITLE
# ------------------------------------------------------------

def split_title(m) =
  if
    string.length(m["artist"]) <= 0
  then
    # Artist - Title
    if
      string.contains(
        substring=
          " - ",
        m["title"]
      )
    then
      let (a, t) =
        string.split.first(
          separator=
            " - ",
          m["title"]
        )

      artist.set(string.trim(a))
      title.set(string.trim(t))

      log_level_3("rec#" ^ string(counter()) ^
          " Splitted %title% to %artist%,%title%")

      log_level_3("rec#" ^ string(counter()) ^
          " Artist: " ^
          artist())

      log_level_3("rec#" ^ string(counter()) ^
          " Title : " ^
          title())
    end

    # Artist ? Title
    if
      string.contains(
        substring=
          " ? ",
        m["title"]
      )
    then
      let (a, t) =
        string.split.first(
          separator=
            " ? ",
          m["title"]
        )

      artist.set(string.trim(a))
      title.set(string.trim(t))

      log_level_3("rec#" ^ string(counter()) ^
          " Splitted %title% to %artist%,%title%")

      log_level_3("rec#" ^ string(counter()) ^
          " Artist: " ^
          artist())

      log_level_3(" Title : " ^
          title())
    end

    # Strip after |
    if
      string.contains(
        substring=
          " | ",
        title()
      )
    then
      let (l, r) =
        string.split.first(
          separator=
            " | ",
          title()
        )

      title.set(string.trim(l))

      log_level_3("rec#" ^ string(counter()) ^
          " Stripped from %title%: | " ^
          r)

      log_level_3("rec#" ^ string(counter()) ^
          " Title : " ^
          title())
    end

    # Strip after [
    if
      string.contains(
        substring=
          " [",
        title()
      )
    then
      let (l, r) =
        string.split.first(
          separator=
            " [",
          title()
        )

      title.set(string.trim(l))

      log_level_3("rec#" ^ string(counter()) ^
          " Stripped from %title%: [" ^
          r)

      log_level_3("rec#" ^ string(counter()) ^
          " Title : " ^
          title())
    end

    # Strip after -
    if
      string.contains(
        substring=
          " - ",
        title()
      )
    then
      let (l, r) =
        string.split.first(
          separator=
            " - ",
          title()
        )

      title.set(string.trim(l))

      log_level_3("rec#" ^ string(counter()) ^
          " Stripped from %title%: - " ^
          r)

      log_level_3("rec#" ^ string(counter()) ^
          " Title : " ^
          title())
    end
  end
end

# ------------------------------------------------------------
# PROCESS METADATA
# ------------------------------------------------------------

def process_metadata(m) =
  artist.set("")
  title.set("")

  split_title(m)

  if
    (artist() != "") and (title() != "")
  then
    [("artist", artist()), ("title", title())]
  elsif (artist() == "") and (title() != "") then [("title", title())]
  else
    []
  end
end

# ------------------------------------------------------------
# ADD COMMENT / URL
# ------------------------------------------------------------

def add_metadata(m) =
  comment = m["comment"]
  streamurl = m["urlx"]

  [
    (
      "comment",
      "#{comment} - ripped with liquidsoap-record - from:  " ^
        urlx()
    ),
    ("url", "#{streamurl}")
  ]
end

# ------------------------------------------------------------
# DOWNLOAD COVER
# ------------------------------------------------------------

def download_cover(m, covername) =
  cover.set("")

  # Metadata cover URL
  if
    (m["urlx"] != "") and string.contains(substring="?", m["urlx"])
  then
    let (q, t) = string.split.first(separator="?", m["urlx"])

    log_level_3("rec#" ^ string(counter()) ^
        " Stripped from %urlx%: [" ^
        t)

    cover.set(q)
  else
    cover.set(m["urlx"])
  end

  # Download metadata cover
  if
    (cover() != "")
  and

      (
        string.contains(suffix="jpg", cover())
      or
        string.contains(suffix="png", cover())
      )

  then
    cov = file.download(filename=covername, cover())

    log_level_3("rec#" ^ string(counter()) ^
        " FOUND COVER (url): " ^
        string(cov) ^
        " : " ^
        cover())
  end

  # TuneIn cover
  if
    string.length(tunein_id()) > 2
  then
    try
      tjson =
        http.get(
          "https://feed.tunein.com/profiles/" ^ tunein_id() ^
            "/nowPlaying?junk=" ^
            string(random.int())
        )

      let json.parse ({Secondary} : {Secondary: {Image: string}}) = tjson

      cover.set(string(Secondary.Image))

      cov2 = file.download(filename=covername, cover())

      log_level_3("rec#" ^ string(counter()) ^
          " FOUND COVER (tunein): " ^
          string(cov2) ^
          " : " ^
          cover())

      if
        relay == "1"
      then
        icy.update_metadata(
          host=hostx,
          port=int_of_string(port),
          user="source",
          password=password,
          mount="stream",
          [("artist", artist()), ("title", title()), ("url", cover())]
        )
      end
    catch err do
      log_level_3("Failed to get image (tunein) - with error: #{err.message}")
    end

  # Deezer cover (fallback when no TuneIn ID is configured)
  elsif
    (m["artist"] != "") and (m["title"] != "")
  then
    try
      dquery = "artist:\"" ^ m["artist"] ^ "\" track:\"" ^ m["title"] ^ "\""

      djson =
        http.get(
          normalize_url=true,
          "https://api.deezer.com/search?limit=1&q=" ^
            dquery
        )

      let json.parse ({data = [d1]} : {data: [{album: {cover_xl: string}}]}) = djson

      cover.set(d1.album.cover_xl)

      cov3 = file.download(filename=covername, cover())

      log_level_3("rec#" ^ string(counter()) ^
          " FOUND COVER (deezer): " ^
          string(cov3) ^
          " : " ^
          cover())

      if
        relay == "1"
      then
        icy.update_metadata(
          host=hostx,
          port=int_of_string(port),
          user="source",
          password=password,
          mount="stream",
          [("artist", artist()), ("title", title()), ("url", cover())]
        )
      end
    catch err do
      log_level_3("Failed to get image (deezer) - with error: #{err.message}")
    end
  end
end

# ------------------------------------------------------------
# BASE FILENAME
# ------------------------------------------------------------

filename =
  ref(
    time.string(
      "#{directory}/" ^ folder() ^ "/%Y-%m-%d_%H-%M-%S." ^ ext() ^ ".rec#s"
    )
  )

nowrecording.set(time.string("%Y-%m-%d_%H-%M-%S." ^ ext() ^ ".rec#s"))

# ------------------------------------------------------------
# HANDLE METADATA / REOPEN FILE
# ------------------------------------------------------------

def handle_metadata(m) =
  if
    singlex != "1"
  then
    log_level_3("rec#" ^ string(counter()) ^
        " NEW METADATA " ^
        string(m))

    # Artist + Title
    if
      (m["artist"] != "")
    and
      (m["title"] != "")
    and
      ((m["artist"] != tmp_artist()) or (m["title"] != tmp_title()))
    then
      log_level_3("rec#" ^ string(counter()) ^
          " RE-OPEN ARTIST - TITLE")

      ref.incr(counter)

      tmp_artist.set(m["artist"])
      tmp_title.set(m["title"])

      f_artist = remove_illegal(m["artist"])
      f_title = remove_illegal(m["title"])

      filename.set(
        "#{directory}/" ^ folder() ^
          "/#{f_artist} - #{f_title}." ^
          ext() ^
          ".rec#" ^
          string(counter())
      )

      nowrecording.set(
        "#{f_artist} - #{f_title}." ^
          ext() ^
          ".rec#" ^
          string(counter())
      )

      if
        covers == "1"
      then
        thread.run(
          delay=5.,
          {
            download_cover(
              m,
              "#{directory}/" ^ folder() ^ "/rec#" ^ string(counter()) ^
                ".cover"
            )
          }
        )
      end

      log_level_2("rec#" ^ string(counter()) ^
          " New Track Detected. Recording.. " ^
          "#{f_artist} - #{f_title}." ^
          ext())

      log_level_2("-- press CTRL-C to stop/exit --")

      true
    elsif
      # Title only

      (m["artist"] == "") and (m["title"] != "") and (m["title"] != tmp_title())
    then
      log_level_3("rec#" ^ string(counter()) ^
          " RE-OPEN TITLE")

      ref.incr(counter)

      tmp_title.set(m["title"])

      f_title = remove_illegal(m["title"])

      filename.set(
        "#{directory}/" ^ folder() ^ "/#{f_title}." ^ ext() ^ ".rec#" ^
          string(counter())
      )

      nowrecording.set("#{f_title}." ^ ext() ^ ".rec#" ^ string(counter()))

      log_level_2("rec#" ^ string(counter()) ^
          " New Track Detected. Recording.. " ^
          "#{f_title}." ^
          ext())

      log_level_2("-- press CTRL-C to stop/exit --")

      true
    else
      log_level_3("rec#" ^ string(counter()) ^
          " FALSE - NOT RE-OPENING")

      false
    end
  else
    false
  end
end

def handle_file(f) =
  # --------------------------------------------------------
  # INITIALIZE
  # --------------------------------------------------------

  let tfilename = ref(path.remove_extension(f))
  let f_duration = ref(0.)

  let tno = file.extension(leading_dot=false, f)

  let c = "#{directory}/" ^ folder() ^ "/" ^ tno ^ ".cover"

  let tmp_filename = "#{directory}/" ^ folder() ^ "/" ^ tno ^ ".tmp"

  let tmp_ext_filename = "#{directory}/" ^ folder() ^ "/" ^ tno ^ "." ^ ext()

  let metaname = tmp_filename ^ ".cover.meta"
  let copy_ok = ref(false)
  let process_ok = ref(false)
  let final_copy_ok = ref(false)

  # --------------------------------------------------------
  # COPY SOURCE TO TEMP
  # --------------------------------------------------------

  try
    file.copy(f, tmp_filename)

    copy_ok.set(true)

    log_level_3(tno ^
        " Source copied to temporary file: " ^
        tmp_filename)
  catch err do
    copy_ok.set(false)

    log_level_1(tno ^
        " ERROR copying source to temporary file: " ^
        "#{err.message}")
  end

  # --------------------------------------------------------
  # PROCESS ONLY IF SOURCE COPY SUCCEEDED
  # --------------------------------------------------------

  if
    copy_ok()
  then
    try
      # ----------------------------------------------------
      # FLAC + COVER
      # ----------------------------------------------------

      if
        (ext() == "flac") and (file.exists(c))
      then
        log_level_3(tno ^
            " FFMPEG-reprocess (FLAC) with COVER " ^
            f)

        let p =
          process.run(
            "ffmpeg -y -v quiet " ^
              "-i " ^
              process.quote(tmp_filename) ^
              " -i " ^
              process.quote(c) ^
              " -map 0:a -map 1 " ^
              "-metadata:s:v title=\"Album cover\" " ^
              "-metadata:s:v comment=\"Cover (front)\" " ^
              "-disposition:v attached_pic " ^
              process.quote(tmp_ext_filename)
          )

        if
          (p.status == "exit")
        and
          (p.status.code == 0)
        and
          file.exists(tmp_ext_filename)
        then
          process_ok.set(true)

          log_level_3(tno ^
              " FFmpeg FLAC + COVER SUCCESS - exit code: " ^
              string(p.status.code))
        else
          process_ok.set(false)

          log_level_1(tno ^
              " FFmpeg FLAC + COVER FAILED - status: " ^
              string(p.status) ^
              " code: " ^
              string(p.status.code) ^
              " stderr: " ^
              p.stderr)
        end
      end

      # ----------------------------------------------------
      # FLAC WITHOUT COVER
      # ----------------------------------------------------

      if
        (ext() == "flac") and not file.exists(c)
      then
        log_level_3(tno ^
            " FFMPEG-reprocess (FLAC) " ^
            f)

        let p =
          process.run(
            "ffmpeg -y -v quiet " ^
              "-i " ^
              process.quote(tmp_filename) ^
              " " ^
              process.quote(tmp_ext_filename)
          )

        if
          (p.status == "exit")
        and
          (p.status.code == 0)
        and
          file.exists(tmp_ext_filename)
        then
          process_ok.set(true)

          log_level_3(tno ^
              " FFmpeg FLAC SUCCESS - exit code: " ^
              string(p.status.code))
        else
          process_ok.set(false)

          log_level_1(tno ^
              " FFmpeg FLAC FAILED - status: " ^
              string(p.status) ^
              " code: " ^
              string(p.status.code) ^
              " stderr: " ^
              p.stderr)
        end
      end

      # ----------------------------------------------------
      # AAC / M4A + COVER
      # ----------------------------------------------------

      if
        (ext() == "m4a") and (file.exists(c))
      then
        log_level_3(tno ^
            " FFMPEG-reprocess (AAC) with COVER " ^
            f)

        let p =
          process.run(
            "ffmpeg -y -v quiet " ^
              "-i " ^
              process.quote(tmp_filename) ^
              " -i " ^
              process.quote(c) ^
              " -map 0:a:0 -map 1:v:0 " ^
              "-filter:v \"scale=w=500:h=500,format=yuvj420p\" " ^
              "-c:a copy -c:v mjpeg " ^
              "-disposition:v:0 attached_pic " ^
              process.quote(tmp_ext_filename)
          )

        if
          (p.status == "exit")
        and
          (p.status.code == 0)
        and
          file.exists(tmp_ext_filename)
        then
          process_ok.set(true)

          log_level_3(tno ^
              " FFmpeg M4A + COVER SUCCESS - exit code: " ^
              string(p.status.code))
        else
          process_ok.set(false)

          log_level_1(tno ^
              " FFmpeg M4A + COVER FAILED - status: " ^
              string(p.status) ^
              " code: " ^
              string(p.status.code) ^
              " stderr: " ^
              p.stderr)
        end
      end

      # ----------------------------------------------------
      # AAC / M4A WITHOUT COVER
      # ----------------------------------------------------

      if
        (ext() == "m4a") and not file.exists(c)
      then
        log_level_3(tno ^
            " FFMPEG-reprocess (AAC) " ^
            f)

        let p =
          process.run(
            "ffmpeg -y -v quiet " ^
              "-i " ^
              process.quote(tmp_filename) ^
              " -c:a copy " ^
              process.quote(tmp_ext_filename)
          )

        if
          (p.status == "exit")
        and
          (p.status.code == 0)
        and
          file.exists(tmp_ext_filename)
        then
          process_ok.set(true)

          log_level_3(tno ^
              " FFmpeg M4A SUCCESS - exit code: " ^
              string(p.status.code))
        else
          process_ok.set(false)

          log_level_1(tno ^
              " FFmpeg M4A FAILED - status: " ^
              string(p.status) ^
              " code: " ^
              string(p.status.code) ^
              " stderr: " ^
              p.stderr)
        end
      end

      # ----------------------------------------------------
      # MP3 + COVER
      # ----------------------------------------------------

      if
        (ext() == "mp3") and (file.exists(c))
      then
        log_level_3(tno ^
            " FFMPEG-reprocess (MP3) with COVER " ^
            f)

        let p =
          process.run(
            "ffmpeg -y -v quiet " ^
              "-i " ^
              process.quote(tmp_filename) ^
              " -i " ^
              process.quote(c) ^
              " -map 0:a:0 -map 1:v:0 " ^
              "-id3v2_version 3 " ^
              "-metadata:s:v title=\"Album cover\" " ^
              "-metadata:s:v comment=\"Cover (front)\" " ^
              "-c:a copy " ^
              process.quote(tmp_ext_filename)
          )

        if
          (p.status == "exit")
        and
          (p.status.code == 0)
        and
          file.exists(tmp_ext_filename)
        then
          process_ok.set(true)

          log_level_3(tno ^
              " FFmpeg MP3 + COVER SUCCESS - exit code: " ^
              string(p.status.code))
        else
          process_ok.set(false)

          log_level_1(tno ^
              " FFmpeg MP3 + COVER FAILED - status: " ^
              string(p.status) ^
              " code: " ^
              string(p.status.code) ^
              " stderr: " ^
              p.stderr)
        end
      end

      # ----------------------------------------------------
      # MP3 WITHOUT COVER
      # ----------------------------------------------------

      if
        (ext() == "mp3") and not file.exists(c)
      then
        log_level_3(tno ^
            " FFMPEG-reprocess (MP3) " ^
            f)

        let p =
          process.run(
            "ffmpeg -y -v quiet " ^
              "-i " ^
              process.quote(tmp_filename) ^
              " -c:a copy " ^
              process.quote(tmp_ext_filename)
          )

        if
          (p.status == "exit")
        and
          (p.status.code == 0)
        and
          file.exists(tmp_ext_filename)
        then
          process_ok.set(true)

          log_level_3(tno ^
              " FFmpeg MP3 SUCCESS - exit code: " ^
              string(p.status.code))
        else
          process_ok.set(false)

          log_level_1(tno ^
              " FFmpeg MP3 FAILED - status: " ^
              string(p.status) ^
              " code: " ^
              string(p.status.code) ^
              " stderr: " ^
              p.stderr)
        end
      end

      # ----------------------------------------------------
      # OPUS + COVER
      # ----------------------------------------------------

      if
        (ext() == "opus") and (file.exists(c))
      then
        log_level_1(tno ^
            " FFMPEG-reprocess (OPUS) with COVER " ^
            f)

        let pm =
          process.run(
            "python3 " ^
              process.quote("build_cover_metadata.py") ^
              " " ^
              process.quote(c) ^
              " " ^
              process.quote(metaname)
          )

        let p =
          if
            (pm.status == "exit")
          and
            (pm.status.code == 0)
          and
            file.exists(metaname)
          then
            process.run(
              "ffmpeg -y -v quiet " ^
                "-i " ^
                process.quote(tmp_filename) ^
                " -i " ^
                process.quote(metaname) ^
                " -map_metadata 1 -map 0:a -c:a copy " ^
                process.quote(tmp_ext_filename)
            )
          else
            log_level_3(tno ^
                " Failed to build METADATA_BLOCK_PICTURE - stderr: " ^
                pm.stderr)

            process.run(
              "ffmpeg -y -v quiet " ^
                "-i " ^
                process.quote(tmp_filename) ^
                " -c:a copy " ^
                process.quote(tmp_ext_filename)
            )
          end

        if
          (p.status == "exit")
        and
          (p.status.code == 0)
        and
          file.exists(tmp_ext_filename)
        then
          process_ok.set(true)

          log_level_1(tno ^
              " FFmpeg OPUS + COVER SUCCESS - exit code: " ^
              string(p.status.code))
        else
          process_ok.set(false)

          log_level_3(tno ^
              " FFmpeg OPUS + COVER FAILED - status: " ^
              string(p.status) ^
              " code: " ^
              string(p.status.code) ^
              " stderr: " ^
              p.stderr)
        end
      end
      # ----------------------------------------------------
      # OPUS WITHOUT COVER
      # ----------------------------------------------------

      if
        (ext() == "opus") and not file.exists(c)
      then
        log_level_3(tno ^
            " FFMPEG-reprocess (OPUS) " ^
            f)

        let p =
          process.run(
            "ffmpeg -y -v quiet " ^
              "-i " ^
              process.quote(tmp_filename) ^
              " -c:a copy " ^
              process.quote(tmp_ext_filename)
          )

        if
          (p.status == "exit")
        and
          (p.status.code == 0)
        and
          file.exists(tmp_ext_filename)
        then
          process_ok.set(true)

          log_level_3(tno ^
              " FFmpeg OPUS SUCCESS - exit code: " ^
              string(p.status.code))
        else
          process_ok.set(false)

          log_level_1(tno ^
              " FFmpeg OPUS FAILED - status: " ^
              string(p.status) ^
              " code: " ^
              string(p.status.code) ^
              " stderr: " ^
              p.stderr)
        end
      end

      # ----------------------------------------------------
      # VORBIS / OGG + COVER
      # ----------------------------------------------------

      if
        (ext() == "ogg") and (file.exists(c))
      then
        log_level_1(tno ^
            " FFMPEG-reprocess (VORBIS) with COVER " ^
            f)

        let pm =
          process.run(
            "python3 " ^
              process.quote("build_cover_metadata.py") ^
              " " ^
              process.quote(c) ^
              " " ^
              process.quote(metaname)
          )

        let p =
          if
            (pm.status == "exit")
          and
            (pm.status.code == 0)
          and
            file.exists(metaname)
          then
            process.run(
              "ffmpeg -y -v quiet " ^
                "-i " ^
                process.quote(tmp_filename) ^
                " -i " ^
                process.quote(metaname) ^
                " -map_metadata 1 -map 0:a -c:a copy " ^
                process.quote(tmp_ext_filename)
            )
          else
            log_level_3(tno ^
                " Failed to build METADATA_BLOCK_PICTURE - stderr: " ^
                pm.stderr)

            process.run(
              "ffmpeg -y -v quiet " ^
                "-i " ^
                process.quote(tmp_filename) ^
                " -c:a copy " ^
                process.quote(tmp_ext_filename)
            )
          end

        if
          (p.status == "exit")
        and
          (p.status.code == 0)
        and
          file.exists(tmp_ext_filename)
        then
          process_ok.set(true)

          log_level_1(tno ^
              " FFmpeg OGG + COVER SUCCESS - exit code: " ^
              string(p.status.code))
        else
          process_ok.set(false)

          log_level_3(tno ^
              " FFmpeg OGG + COVER FAILED - status: " ^
              string(p.status) ^
              " code: " ^
              string(p.status.code) ^
              " stderr: " ^
              p.stderr)
        end
      end

      # ----------------------------------------------------
      # VORBIS / OGG WITHOUT COVER
      # ----------------------------------------------------

      if
        (ext() == "ogg") and not file.exists(c)
      then
        log_level_3(tno ^
            " FFMPEG-reprocess (VORBIS) " ^
            f)

        let p =
          process.run(
            "ffmpeg -y -v quiet " ^
              "-i " ^
              process.quote(tmp_filename) ^
              " -c:a copy " ^
              process.quote(tmp_ext_filename)
          )

        if
          (p.status == "exit")
        and
          (p.status.code == 0)
        and
          file.exists(tmp_ext_filename)
        then
          process_ok.set(true)

          log_level_3(tno ^
              " FFmpeg OGG SUCCESS - exit code: " ^
              string(p.status.code))
        else
          process_ok.set(false)

          log_level_1(tno ^
              " FFmpeg OGG FAILED - status: " ^
              string(p.status) ^
              " code: " ^
              string(p.status.code) ^
              " stderr: " ^
              p.stderr)
        end
      end
    catch err do
      process_ok.set(false)

      log_level_1(tno ^
          " EXCEPTION during FFMPEG processing: " ^
          "#{err.message}")
    end

    # --------------------------------------------------------
    # ONLY CONTINUE IF FFMPEG SUCCEEDED
    # AND OUTPUT FILE EXISTS
    # --------------------------------------------------------

    if
      process_ok() and file.exists(tmp_ext_filename)
    then
      # ------------------------------------------------------
      # GET DURATION
      # ------------------------------------------------------

      try
        f_duration.set(
          null.get(
            default=0.,
            request.duration(resolve_metadata=false, tmp_ext_filename)
          )
        )
      catch err do
        log_level_2(tno ^
            " request.duration failed: " ^
            "#{err.message}")

        f_duration.set(0.)
      end

      log_level_3(tno ^
          " Request duration: " ^
          string(f_duration()))

      # ------------------------------------------------------
      # FFPROBE DURATION FALLBACK
      # ------------------------------------------------------

      if
        f_duration() == 0.
      then
        try
          log_level_3(tno ^
              " FFPROBE duration fallback (request=0)")

          d =
            process.read(
              "ffprobe -v quiet " ^
                "-print_format json " ^
                "-select_streams a:0 " ^
                "-show_entries format=duration " ^
                "-of json=compact=1 " ^
                process.quote(tmp_ext_filename)
            )

          let json.parse ({format = d0} : {format: {duration: string}}) = d

          f_duration.set(float_of_string(d0.duration))
        catch err do
          log_level_3(tno ^
              " FFPROBE failed to get duration!! - keep file - with error: " ^
              "#{err.message}")

          f_duration.set(16.)
        end
      end

      # ------------------------------------------------------
      # POST DURATION
      # ------------------------------------------------------

      log_level_3(tno ^
          " POST DURATION " ^
          string(f_duration()))

      log_level_3(tno ^
          " CLOSE " ^
          string(f_duration()) ^
          " [" ^
          format_time(float_of_string(string(f_duration()))) ^
          "]  " ^
          f)

      # ------------------------------------------------------
      # FINAL FILENAME / COLLISION PROTECTION
      # ------------------------------------------------------

      if
        file.exists(tfilename())
      then
        tfilename.set(time.string(tfilename() ^ "-%Y-%m-%d_%H-%M-%S." ^ ext()))
      end

      # ------------------------------------------------------
      # FINAL COPY
      # DO NOT DELETE ORIGINAL UNTIL THIS SUCCEEDS
      # ------------------------------------------------------

      final_copy_ok.set(false)

      try
        file.copy(tmp_ext_filename, tfilename())

        if
          file.exists(tfilename())
        then
          final_copy_ok.set(true)

          log_level_3(tno ^
              " Final file copy SUCCESS: " ^
              tfilename())
        else
          final_copy_ok.set(false)

          log_level_1(tno ^
              " ERROR: final file copy returned but destination does not exist: \
               " ^
              tfilename())
        end
      catch err do
        final_copy_ok.set(false)

        log_level_1(tno ^
            " ERROR copying final file: " ^
            "#{err.message}")
      end

      # ------------------------------------------------------
      # ONLY CLEAN ORIGINAL/TEMPS AFTER FINAL COPY SUCCEEDED
      # ------------------------------------------------------

      if
        final_copy_ok()
      then
        # ----------------------------------------------------
        # REMOVE ORIGINAL SOURCE
        # ----------------------------------------------------

        if
          file.exists(f)
        then
          try
            file.remove(f)
          catch err do
            log_level_2(tno ^
                " WARNING: could not remove source file: " ^
                "#{err.message}")
          end
        end

        # ----------------------------------------------------
        # REMOVE TEMP SOURCE
        # ----------------------------------------------------

        if
          file.exists(tmp_filename)
        then
          try
            file.remove(tmp_filename)
          catch err do
            log_level_2(tno ^
                " WARNING: could not remove temporary source: " ^
                "#{err.message}")
          end
        end

        # ----------------------------------------------------
        # REMOVE COVER
        # ----------------------------------------------------

        if
          file.exists(c)
        then
          try
            file.remove(c)
          catch err do
            log_level_2(tno ^
                " WARNING: could not remove cover: " ^
                "#{err.message}")
          end
        end

        # ----------------------------------------------------
        # REMOVE COVER METADATA FILE
        # ----------------------------------------------------

        if
          file.exists(metaname)
        then
          try
            file.remove(metaname)
          catch err do
            log_level_3(tno ^
                " WARNING: could not remove cover metadata file: " ^
                "#{err.message}")
          end
        end

        # ----------------------------------------------------
        # REMOVE PROCESSED TEMP
        # ----------------------------------------------------

        if
          file.exists(tmp_ext_filename)
        then
          try
            file.remove(tmp_ext_filename)
          catch err do
            log_level_2(tno ^
                " WARNING: could not remove processed temp file: " ^
                "#{err.message}")
          end
        end

        # ----------------------------------------------------
        # SHORT FRAGMENT HANDLING
        # ----------------------------------------------------

        if
          (f_duration() < 15.) and (keep == "0")
        then
          if
            file.exists(tfilename())
          then
            try
              file.remove(tfilename())

              log_level_3(tno ^
                  " Deleted unwanted fragment " ^
                  tfilename())
            catch err do
              log_level_2(tno ^
                  " WARNING: could not delete unwanted fragment: " ^
                  "#{err.message}")
            end
          end
        elsif
          (f_duration() < 15.) and (keep == "1")
        then
          try
            file.mkdir("#{directory}/" ^ folder() ^ "/incomplete")

            file.move(tfilename(), "#{directory}/" ^ folder() ^ "/incomplete")

            log_level_3(tno ^
                " Moved unwanted fragment ID " ^
                tno ^
                " to incomplete. Filename " ^
                tfilename())
          catch err do
            log_level_2(tno ^
                " WARNING: could not move unwanted fragment to incomplete: " ^
                "#{err.message}")
          end
        elsif
          f_duration() > 15.
        then
          log_level_3(tno ^
              " Finished. Keeping file : " ^
              tfilename())
        end
      else
        # ----------------------------------------------------
        # FINAL COPY FAILED
        # IMPORTANT: KEEP EVERYTHING
        # ----------------------------------------------------

        log_level_1(tno ^
            " FINAL COPY FAILED - keeping original recording: " ^
            f)

        log_level_1(tno ^
            " Processed temporary file retained: " ^
            tmp_ext_filename)
      end
    else
      # ------------------------------------------------------
      # FFMPEG FAILED
      # IMPORTANT: KEEP ORIGINAL RECORDING
      # ------------------------------------------------------

      log_level_1(tno ^
          " FFMPEG FAILED - keeping original recording: " ^
          f)

      # ------------------------------------------------------
      # CLEAN FAILED TEMP SOURCE
      # ------------------------------------------------------

      if
        file.exists(tmp_filename)
      then
        try
          file.remove(tmp_filename)
        catch err do
          log_level_2(tno ^
              " WARNING: could not remove failed temp file: " ^
              "#{err.message}")
        end
      end
    end
  else
    # --------------------------------------------------------
    # SOURCE COPY FAILED
    # --------------------------------------------------------

    log_level_1(tno ^
        " SOURCE COPY FAILED - keeping original recording: " ^
        f)
  end
end

# ------------------------------------------------------------
# ASYNC FILE POST-PROCESSING
# ------------------------------------------------------------

def handle_file_async(f) =
  log_level_3("QUEUE POST-PROCESSING: " ^
      f)

  thread.run(fast=false, {handle_file(f)})
end

# ------------------------------------------------------------
# SHUTDOWN-AWARE DISPATCH
# ------------------------------------------------------------
# During normal recording, track-boundary closes (reopen_on_metadata) go
# through handle_file_async so post-processing doesn't block the recorder.
# On shutdown, the final close should be processed synchronously so the
# process doesn't exit before post-processing (cover art, transcode, etc.)
# has actually finished.

shutting_down = ref(false)

def handle_file_dispatch(f) =
  if
    shutting_down()
  then
    log_level_3("SHUTDOWN - PROCESSING SYNCHRONOUSLY: " ^
        f)

    handle_file(f)
  else
    handle_file_async(f)
  end
end

# ------------------------------------------------------------
# STREAM COPY MODE
# ------------------------------------------------------------

if
  transcode == "0"
then
  log_level_2("STREAM COPY MODE")

  log_level_2("Recording.. " ^
      filename())

  log_level_2("--press CTRL-C to stop/exit.")

  # Source
  s1 = buffer(buffer=5.0, input.ffmpeg(self_sync=true, poll_delay=0.1, urlx()))

  # Metadata
  s1 = metadata.map(lower_ARTIST, s1)

  s1 = metadata.map(lower_TITLE, s1)

  s1 = metadata.map(strip=true, clean_metadata, s1)

  s1 = metadata.map(process_metadata, s1)

  s1 = metadata.map(add_metadata, s1)

  # File writer
  f1 =
    output.file(
      %ffmpeg(format = cformat(), %audio.copy),
      filename,
      s1,
      reopen_on_metadata=handle_metadata,
      on_close=handle_file_dispatch,
#      reopen_on_error=fun (_) -> 0.,
      append=true,
      fallible=true
    )

  # Stop the file output cleanly on shutdown (CTRL-C, /stop_all, timeout
  # watchdog). Setting shutting_down first makes handle_file_dispatch run
  # handle_file synchronously (not via the async thread) so the process
  # doesn't exit before post-processing of the final file has finished.
  def shutdown_f1() =
    shutting_down.set(true)
    f1.stop()
  end

  on_shutdown(shutdown_f1)



  # ----------------------------------------------------------
  # PORTAUDIO
  # ----------------------------------------------------------

%ifdef output.portaudio
  if
    (listen == "1") and (device == "portaudio")
  then
    x = output.portaudio(mksafe(ffmpeg.decode.audio(s1)))
  end
%endif

  # ----------------------------------------------------------
  # ALSA
  # ----------------------------------------------------------

%ifdef output.alsa
  if
    (listen == "1") and (device == "alsa")
  then
    x = output.alsa(mksafe(ffmpeg.decode.audio(s1)))
  end
%endif

  # ----------------------------------------------------------
  # PROGRESS LOG
  # ----------------------------------------------------------

  #Now Recording info

  thread.run(
    every=30.,
    fun () ->
      log_level_2("Recording " ^
          format_time(s1.time()) ^
          " " ^
          nowrecording())
  )

  #Clocks

%ifdef clock.dump
  thread.run(
    every=30., fun () -> log_level_4(clock.dump())
  )
%endif

  # ----------------------------------------------------------
  # ICECAST RELAY
  # ----------------------------------------------------------

  if
    relay == "1"
  then
    output.icecast(
      %ffmpeg(
        format = "adts",
        %audio(samplerate = 44100, codec = "aac", b = "320k")
      ),
      host=hostx,
      port=int_of_string(port),
      fallible=false,
      name="LSR relay",
      password=password,
      mount="stream",
      #send_icy_metadata=false,
      mksafe(ffmpeg.decode.audio(s1))
    )
  end

  # ----------------------------------------------------------
  # WATCHDOG
  # ----------------------------------------------------------

  def watchdog_s1() =
    if
      (timeout() != "0") and (s1.time() > string.to_float(timeout()))
    then
      log_level_2("Defined Timeout achieved , Exiting ...")

      shutdown()
    end
  end

  thread.run(every=1., watchdog_s1)

  # ------------------------------------------------------------
  # STREAM TRANSCODING MODE
  # ------------------------------------------------------------
else
  log_level_2("STREAM TRANSCODING MODE")

  log_level_2("Recording.. " ^
      filename())

  log_level_2("--press CTRL-C to stop/exit.")

  # Source
  s2 = buffer(buffer=5.0, input.ffmpeg(self_sync=true, poll_delay=0.1, urlx()))

  # Give the buffered recorder source its own stable CPU clock.
  clock.assign_new(sync="cpu", [s2])

  # Metadata
  s2 = metadata.map(lower_ARTIST, s2)

  s2 = metadata.map(lower_TITLE, s2)

  s2 = metadata.map(strip=true, clean_metadata, s2)

  s2 = metadata.map(process_metadata, s2)

  s2 = metadata.map(add_metadata, s2)

  # File writer
  f2 =
    output.file(
      %ffmpeg(
        format = "#{formatx}",
        %audio(
          samplerate = "#{samplerate}",
          codec = "#{codec}",
          b = "#{bitrate}"
        )
      ),
      filename,
      s2,
      reopen_on_metadata=handle_metadata,
      on_close=handle_file_dispatch,
#      reopen_on_error=fun (_) -> 0.,
      append=true,
      fallible=true
    )

  # Stop the file output cleanly on shutdown (CTRL-C, /stop_all, timeout
  # watchdog). Setting shutting_down first makes handle_file_dispatch run
  # handle_file synchronously (not via the async thread) so the process
  # doesn't exit before post-processing of the final file has finished.
  def shutdown_f2() =
    shutting_down.set(true)
    f2.stop()
  end

  on_shutdown(shutdown_f2)


  # ----------------------------------------------------------
  # PORTAUDIO
  # ----------------------------------------------------------

%ifdef output.portaudio
  if
    (listen == "1") and (device == "portaudio")
  then
    x = output.portaudio(mksafe(s2))
  end
%endif

  # ----------------------------------------------------------
  # ALSA
  # ----------------------------------------------------------

%ifdef output.alsa
  if (listen == "1") and (device == "alsa") then x = output.alsa(mksafe(s2)) end
%endif

  # ----------------------------------------------------------
  # ICECAST RELAY
  # ----------------------------------------------------------

  if
    relay == "1"
  then
    output.icecast(
      %ffmpeg(
        format = "adts",
        %audio(samplerate = 44100, codec = "aac", b = "320k")
      ),
      host=hostx,
      port=int_of_string(port),
      fallible=false,
      name="LSR relay",
      password=password,
      mount="stream",
      #send_icy_metadata=false,
      mksafe(s2)
    )
  end

  # ----------------------------------------------------------
  # PROGRESS LOG
  # ----------------------------------------------------------

  thread.run(
    every=30.,
    fun () ->
      log_level_2("Recording " ^
          format_time(s2.time()) ^
          " " ^
          nowrecording())
  )

  # ----------------------------------------------------------
  # WATCHDOG
  # ----------------------------------------------------------

  def watchdog_s2() =
    if
      (timeout() != "0") and (s2.time() > string.to_float(timeout()))
    then
      log_level_2("Defined Timeout achieved , Exiting ...")

      shutdown()
    end
  end

  thread.run(every=1., watchdog_s2)
end

# ------------------------------------------------------------
# HTTP COMMAND SERVER
# ------------------------------------------------------------

settings.harbor.bind_addrs := ["127.0.0.1"]

# Add a STOP endpoint for shutdown
def http_stop_all(_, response) =
  shutdown()
  response.data("Done!")
end

harbor.http.register(
  port=1234,
  method="GET",
  "/stop_all",
  http_stop_all
)
