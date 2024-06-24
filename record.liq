#record.liq
#v.1.0.4

#https://github.com/savonet/liquidsoap/releases

#usage liquidsoap.exe record.liq -- -url "<url>" -dir "<directory>" -t <0> -samplerate "<samplerate>" -format "<format>" -codec "<codec>" -bitrate "<bitrate>" -l <0>

url = ref("")
ext = ref("")
cformat = ref("")
url.set(getopt(default=" ","-url"))
directory = getopt(default=" ","-dir")

transcode = getopt(default="0","-t")
samplerate = getopt(default="44100","-samplerate")
format= getopt(default="mp3","-format")
codec = getopt(default="libmp3lame","-codec")
bitrate = getopt(default="320k","-bitrate")
listen = getopt(default="0","-l")

artist = ref("")
title = ref("")
tmp_artist = ref("")
tmp_title = ref("")

if codec == "libmp3lame" then
ext.set("mp3")
end
if codec == "aac" then
ext.set("m4a")
end
if codec == "flac" then
ext.set("flac")
end
if codec == "libopus" then
ext.set("opus")
end
if codec == "vorbis" then
ext.set("ogg")
end

def split_url
	if string.contains(substring="?", url()) then
	let (u,r) = string.split.first(separator="?", url())
	url.set(u)
	log.important("Stripped %url% after ? of: " ^ r) 
	end
end

split_url

def ffprobe_url()
  codec_name =  process.read("ffprobe.exe -v quiet -print_format json -select_streams a:0 -show_entries stream=codec_name -of default=noprint_wrappers=1:nokey=1 " ^ url())
  codec_name = r/(\r\n|\n|\r)/g.replace(fun(_) -> "",codec_name)
  log.important("ffprobe found codec_name #{codec_name}")
  if codec_name == "mp3" then
  cformat.set("mp3")
  ext.set("mp3")
  end
  if codec_name == "aac" then
  cformat.set("m4a")
  ext.set("m4a")
  end
  if codec_name == "flac" then
  cformat.set("ogg")
  ext.set("ogg")
  end
  if codec_name == "opus" then
  cformat.set("ogg")
  ext.set("opus")
  end
  if codec_name == "vorbis" then
  cformat.set("ogg")
  ext.set("ogg")
  end
end

if transcode == "0" then
ffprobe_url()
end

def remove_illegal(value) =
	str = r/[\?\<\>]/g.replace(fun(_) -> "_",value)
	str = r/[\*<>]/g.replace(fun(_) -> "x",str)
	str = r/[\:\/|\\]/g.replace(fun(_) -> "-",str)
	str = r/[\"]/g.replace(fun(_) -> "''",str)
	str
end

folder = remove_illegal(url())

def split_title(m)
	if string.length(m["artist"]) <= 0 then
		if string.contains(substring=" - ", m["title"]) then
		let (a,t) = string.split.first(separator=" - ", m["title"])
		artist.set(a)
		title.set(t)
		log.important("Splitted %title% to %artist%,%title%")
		log.important("Artist: " ^ artist())
		log.important("Title : " ^ title())
		end
		if string.contains(substring=" | ", title()) then
		let (l,r) = string.split.first(separator=" | ", title())
		title.set(l)
		log.important("Stripped from %title%: | " ^ r)
		log.important("Title : " ^ title())
		end
	end
end

def lower_ARTIST(m)
	if m["ARTIST"] != "" then
	[("artist",m["ARTIST"])]
	else
	[]
	end
end

def lower_TITLE(m)
if m["TITLE"] != "" then
	[("title",m["TITLE"])]
	else
	[]
	end
end

def process_metadata(m)
	artist.set("")
	title.set("")
	split_title(m) 
	if (artist() != "") and (title() != "") then
	[("artist",artist()),("title",title())] 
	else
	[] 
	end
end

def add_metadata(m)
	comment = m["comment"]
	[("comment","#{comment} - ripped with liquidsoap-record")] 
end

filename = ref(time.string("#{directory}/#{folder}/%Y-%m-%d_%H-%M-%S." ^ ext()))

def handle_metadata(m) 
    filename.set(time.string("#{directory}/#{folder}/%Y-%m-%d_%H-%M-%S." ^ ext()))	
	if (m["artist"] != "") and (m["title"] != "") and ((m["artist"] != tmp_artist()) or (m["title"] != tmp_title())) then
	tmp_artist.set(m["artist"])
	tmp_title.set(m["title"])
	f_artist = remove_illegal(m["artist"])
	f_title = remove_illegal(m["title"])
	filename := "#{directory}/#{folder}/#{f_artist} - #{f_title}." ^ ext()
	log.important(string(m))
	log.important("New metadata - Starting #{directory}/#{folder}/#{f_artist} - #{f_title}." ^ ext())	
	true
	else
	log.important("No metadata or the same metadata - not re-opening output")
	false
	end
end

if transcode == "0" then
log.important("Stream COPY")

s1 = input.ffmpeg(url())

s1 = metadata.map(lower_ARTIST, s1)
s1 = metadata.map(lower_TITLE, s1)
s1 = metadata.map(process_metadata, s1)
s1 = metadata.map(add_metadata, s1)

f1 = output.file(%ffmpeg(
  format=cformat(),
  %audio.copy), 
  filename, 
  s1, 
  reopen_on_metadata=handle_metadata, append=true, fallible=true)
  
if listen == "1" then
x = output.portaudio(mksafe(input.http(url())))
end

else

log.important("Stream TRANSCODING")

s2 = input.ffmpeg(url())

s2 = metadata.map(lower_ARTIST, s2)
s2 = metadata.map(lower_TITLE, s2)
s2 = metadata.map(process_metadata, s2)
s2 = metadata.map(add_metadata, s2)

f2 = output.file(%ffmpeg(
  format="#{format}",
  %audio(samplerate = "#{samplerate}", codec = "#{codec}", b = "#{bitrate}")), 
  filename, 
  s2, 
  reopen_on_metadata=handle_metadata, append=true, fallible=true)

if listen == "1" then
x = output.portaudio(mksafe(s2))
end

end

