#record.liq
#v.1.0.7

#https://github.com/savonet/liquidsoap/releases

#usage liquidsoap.exe record.liq -- -url "<url>" -dir "<directory>" -t <0> -samplerate "<samplerate>" -format "<format>" -codec "<codec>" -bitrate "<bitrate>" -l <0> -log <3>

#references-definitions
url = ref("")
ext = ref("")
cformat = ref("")
url.set(getopt(default=" ","-url"))
directory = getopt(default=" ","-dir")
folder = ref("")
transcode = getopt(default="0","-t")
samplerate = getopt(default="44100","-samplerate")
format= getopt(default="mp3","-format")
codec = getopt(default="libmp3lame","-codec")
bitrate = getopt(default="320k","-bitrate")
listen = getopt(default="0","-l")
logoutput = getopt(default="2","-log")
artist = ref("")
title = ref("")
tmp_artist = ref("")
tmp_title = ref("")

#set log level
settings.log.level.set(int_of_string(logoutput))

#set ext for selected codec
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

#remove illegal characters 
def remove_illegal(value) =
	str = r/[\?\<\>]/g.replace(fun(_) -> "_",value)
	str = r/[\*<>]/g.replace(fun(_) -> "x",str)
	str = r/[\:\/|\\]/g.replace(fun(_) -> "-",str)
	str = r/[\"]/g.replace(fun(_) -> "''",str)
	str = r/[\.]/g.replace(fun(_) -> "",str)
	str
end

#strip url after ?
def split_url
	if string.contains(substring="?", url()) then
	let (u,r) = string.split.first(separator="?", url())
	url.set(u)
	log(label="liquidsoap-record", level=2, "Stripped %url% after ? of: " ^ r) 
	end
end

split_url

#folder remove illegal
folder.set(remove_illegal(url()))

#ffprobe icy-name to use as folder name
def ffprobe_name() 
  icy_name =  process.read("ffprobe.exe -v quiet -print_format json -select_streams a:0 -show_entries format=format_tags:format_tags=icy-name -of default=noprint_wrappers=1:nokey=1 " ^ url())
  icy_name = r/(\r\n|\n|\r)/g.replace(fun(_) -> "",icy_name)
  log(label="liquidsoap-record", level=2,"ffprobe icy-name: #{icy_name}")
  if icy_name != "" then
  folder.set(remove_illegal(icy_name))
  end
  log(label="liquidsoap-record", level=2,"Saving to folder: " ^ folder())
end

ffprobe_name()

#ffprobe url to set format,ext of codec (stream copy)
def ffprobe_url() 
try
	j =  process.read("ffprobe.exe -v quiet -print_format json -select_streams a:0 -show_entries stream=codec_name -of json=compact=1 " ^ url())
	let json.parse ({streams = [c1]}: {streams: [{codec_name: string}]}) = j
	codec_name = string(c1.codec_name)
	log(label="liquidsoap-record", level=2,"ffprobe codec_name: #{codec_name}")
  
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
catch err do
    log(label="liquidsoap-record", level=2,"ffprobe failed to get codec_name!!! with error: #{err.message}")
	log(label="liquidsoap-record", level=2,"Is the stream online ??")
	#shutdown()
	end
end

#ffprobe codec for stream copy
if transcode == "0" then
ffprobe_url()
end

#create a m3u playlist in the folder for reference
m3u = ref("#{directory}/" ^ folder())
file.mkdir(m3u())
file.write(data=url(),m3u() ^ "/#listen.m3u")

#split %title% to %artist%,%title% - strip %title% after |
def split_title(m)
	if string.length(m["artist"]) <= 0 then
		if string.contains(substring=" - ", m["title"]) then
		let (a,t) = string.split.first(separator=" - ", m["title"])
		artist.set(a)
		title.set(t)
		log(label="liquidsoap-record", level=3,"Splitted %title% to %artist%,%title%")
		log(label="liquidsoap-record", level=3,"Artist: " ^ artist())
		log(label="liquidsoap-record", level=3,"Title : " ^ title())
		end
		if string.contains(substring=" | ", title()) then
		let (l,r) = string.split.first(separator=" | ", title())
		title.set(l)
		log(label="liquidsoap-record", level=3,"Stripped from %title%: | " ^ r)
		log(label="liquidsoap-record", level=3,"Title : " ^ title())
		end
	end
end

#lowercase %ARTIST%
def lower_ARTIST(m)
	if m["ARTIST"] != "" then
	[("artist",m["ARTIST"])]
	else
	[]
	end
end

#lowercase %TITLE%
def lower_TITLE(m)
	if m["TITLE"] != "" then
	[("title",m["TITLE"])]
	else
	[]
	end
end

#define found metadata
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

#add a comment to metadata
def add_metadata(m)
	comment = m["comment"]
	[("comment","#{comment} - ripped with liquidsoap-record")] 
end

#base filename on start
filename = ref(time.string("#{directory}/" ^ folder() ^ "/%Y-%m-%d_%H-%M-%S." ^ ext()))

#define when to reopen file on new metadata
def handle_metadata(m) 
    filename.set(time.string("#{directory}/" ^ folder() ^ "/%Y-%m-%d_%H-%M-%S." ^ ext()))	
	if (m["artist"] != "") and (m["title"] != "") and ((m["artist"] != tmp_artist()) or (m["title"] != tmp_title())) then
	tmp_artist.set(m["artist"])
	tmp_title.set(m["title"])
	f_artist = remove_illegal(m["artist"])
	f_title = remove_illegal(m["title"])
	filename := "#{directory}/" ^ folder() ^ "/#{f_artist} - #{f_title}." ^ ext()
	log(label="liquidsoap-record", level=3,string(m))
	log(label="liquidsoap-record", level=3,"Recording.. #{directory}/" ^ folder()^ "/#{f_artist} - #{f_title}." ^ ext())
	log(label="liquidsoap-record", level=2,"New Track Detected")	
	log(label="liquidsoap-record", level=2,"Recording.. #{f_artist} - #{f_title}." ^ ext())	
	log(label="liquidsoap-record", level=2,"--press CTRL-C to stop/exit.")
	true
	else
	false
	end
end

#define file operations - delete recorded fragments
def handle_file(f)
	if file.size(f) < 100000 then
	file.remove(f)
	log(label="liquidsoap-record", level=2,"Deleted unwanted fragment " ^ f)
	end
end

#stream copy file writer
if transcode == "0" then
log(label="liquidsoap-record", level=2,"STREAM COPY MODE")
log(label="liquidsoap-record", level=2,"Recording.. " ^ filename())	
log(label="liquidsoap-record", level=2,"--press CTRL-C to stop/exit.")

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
  reopen_on_metadata=handle_metadata, on_close=handle_file, append=true, fallible=true)

#output to portaudio (needs new source input.http - s1 is copy)  
if listen == "1" then
x = output.portaudio(mksafe(input.http(url())))
end

else

#stream transcoding file writer
log(label="liquidsoap-record", level=2,"STREAM TRANSCODING MODE")
log(label="liquidsoap-record", level=2,"Recording.. " ^ filename())	
log(label="liquidsoap-record", level=2,"--press CTRL-C to stop/exit.")

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
  reopen_on_metadata=handle_metadata, on_close=handle_file, append=true, fallible=true)

#output to portaudio (use s2 pcm)
if listen == "1" then
x = output.portaudio(mksafe(s2))
end

end

