#record.liq
#v.1.0.20 2024-09-15

#usage liquidsoap record.liq -- -url "<url>" -dir "<directory>" -transcode <0> -samplerate "<samplerate>" -format "<format>" -codec "<codec>" -bitrate "<bitrate>" -listen <0> -device "<portaudio><alsa>" -log <2> -keep <0>


#references-definitions
url = ref("")
ext = ref("")
cformat = ref("")
codec_name = ref("")
url.set(getopt(default=" ","-url"))
directory = getopt(default=" ","-dir")
folder = ref("")
transcode = getopt(default="0","-transcode")
samplerate = getopt(default="44100","-samplerate")
format= getopt(default="mp3","-format")
codec = getopt(default="libmp3lame","-codec")
bitrate = getopt(default="320k","-bitrate")
listen = getopt(default="0","-listen")
device = getopt(default="portaudio","-device")
logoutput = getopt(default="2","-log")
keep = getopt(default="0","-keep")
artist = ref("")
title = ref("")
tmp_artist = ref("")
tmp_title = ref("")
counter = ref(-1)
nowrecording = ref("")
tfilename = ref("")

#create root directory 					   
file.mkdir(directory)

#set log level
settings.log.level.set(int_of_string(logoutput))

#set ffmpeg log level
settings.ffmpeg.log.verbosity := "error"

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

#strip url after &
def split_url()
	if string.contains(substring="&", url()) then
	let (u,r) = string.split.first(separator="&", url())
	url.set(u)
	log(label="liquidsoap-record", level=2, "Stripped %url% after & of: " ^ r) 
	end
end

split_url()

#folder remove illegal
folder.set(string.trim(remove_illegal(url())))

#ffprobe icy-name to use as folder name
def ffprobe_name() 
  icy_name =  process.read("ffprobe -v quiet -print_format json -select_streams a:0 -show_entries format=format_tags:format_tags=icy-name -of default=noprint_wrappers=1:nokey=1 " ^ url())
  icy_name = r/(\r\n|\n|\r)/g.replace(fun(_) -> "",icy_name)
  log(label="liquidsoap-record", level=2,"ffprobe icy-name: #{icy_name}")
  if icy_name != "" then
  folder.set(string.trim(remove_illegal(icy_name)))
  end
  log(label="liquidsoap-record", level=2,"Saving to folder: " ^ folder())
end

ffprobe_name()

#ffprobe url to set format,ext of codec (stream copy)
def ffprobe_url() 
try
	j =  process.read("ffprobe -v quiet -print_format json -select_streams a:0 -show_entries stream=codec_name -of json=compact=1 " ^ url())
	let json.parse ({streams = [c1]}: {streams: [{codec_name: string}]}) = j
	codec_name.set(string(c1.codec_name))
	log(label="liquidsoap-record", level=2,"ffprobe codec_name: " ^ codec_name())
  
	if codec_name() == "mp3" then
	cformat.set("mp3")
	ext.set("mp3")
	end
	if codec_name() == "aac" then
	cformat.set("mp4")
	ext.set("m4a")
	end
	if codec_name() == "flac" then
	cformat.set("flac")
	ext.set("flac")
	end
	if codec_name() == "opus" then
	cformat.set("ogg")
	ext.set("opus")
	end
	if codec_name() == "vorbis" then
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

def format_time(time)
    seconds = int(time mod 60.)
    seconds_string =
        if seconds < 10 then
            "0" ^ string(seconds)
        else
            string(seconds)
        end
    minutes = int(time / 60.)
    minutes_string =
        if minutes < 10 then
            "0" ^ string(minutes)
        else
            string(minutes)
        end
    minutes_string ^ ":" ^ seconds_string
end

#create a m3u playlist in the folder for reference
m3u = ref("#{directory}/" ^ folder())
file.mkdir(m3u())
file.write(data=url(),m3u() ^ "/#listen.m3u")

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

#split %title% to %artist%,%title% - strip %title% after |
def split_title(m)
	if string.length(m["artist"]) <= 0 then
		if string.contains(substring=" - ", m["title"]) then
		let (a,t) = string.split.first(separator=" - ", m["title"])
		artist.set(string.trim(a))
		title.set(string.trim(t))
		log(label="liquidsoap-record", level=3,"#" ^ string(counter()) ^ " Splitted %title% to %artist%,%title%")
		log(label="liquidsoap-record", level=3,"#" ^ string(counter()) ^ " Artist: " ^ artist())
		log(label="liquidsoap-record", level=3,"#" ^ string(counter()) ^ " Title : " ^ title())
		end
		if string.contains(substring=" | ", title()) then
		let (l,r) = string.split.first(separator=" | ", title())
		title.set(string.trim(l))
		log(label="liquidsoap-record", level=3,"#" ^ string(counter()) ^ " Stripped from %title%: | " ^ r)
		log(label="liquidsoap-record", level=3,"#" ^ string(counter()) ^ " Title : " ^ title())
		end
	end
end

#define found metadata
def process_metadata(m)
	ref.incr(counter)
	artist.set("")
	title.set("")
	split_title(m) 
	if (artist() != "") and (title() != "") then
	[("artist",artist()),("title",title())] 
	elsif (artist() == "") and (title() != "") then
	[("title",title())] 
	else
	[] 
	end
end

#add a comment to metadata
def add_metadata(m)
	comment = m["comment"]
	[("comment","#{comment} - ripped with liquidsoap-record - from:  " ^ url())] 
end

#base filename on start
filename = ref(time.string("#{directory}/" ^ folder() ^ "/%Y-%m-%d_%H-%M-%S." ^ ext()^ ".rec#s"))
nowrecording.set(time.string("[%Y-%m-%d_%H-%M-%S." ^ ext()^ ".rec#s]"))

#define when to reopen file on new metadata
def handle_metadata(m)	
	log(label="liquidsoap-record", level=3,"#" ^ string(counter()) ^ " NEW METADATA " ^ string(m))
	filename.set(time.string("#{directory}/" ^ folder() ^ "/%Y-%m-%d_%H-%M-%S." ^ ext() ^ ".rec#" ^ string(counter())))	
	if (m["artist"] != "") and (m["title"] != "") and ((m["artist"] != tmp_artist()) or (m["title"] != tmp_title())) then
	log(label="liquidsoap-record", level=3,"#" ^ string(counter()) ^ " RE-OPEN ARTIST - TITLE")
	tmp_artist.set(m["artist"])
	tmp_title.set(m["title"])
	f_artist = remove_illegal(m["artist"])
	f_title = remove_illegal(m["title"])
	filename.set("#{directory}/" ^ folder() ^  "/#{f_artist} - #{f_title}." ^ ext() ^ ".rec#" ^ string(counter()))
	nowrecording.set("[#{f_artist} - #{f_title}." ^ ext() ^ ".rec#" ^ string(counter()) ^ "]")
	log(label="liquidsoap-record", level=2,"#" ^ string(counter()) ^ " New Track Detected. Recording.. #{f_artist} - #{f_title}." ^ ext())	
	log(label="liquidsoap-record", level=2,"-- press CTRL-C to stop/exit --")
	true
	elsif (m["artist"] == "") and (m["title"] != "") and (m["title"] != tmp_title()) then
	log(label="liquidsoap-record", level=3,"#" ^ string(counter()) ^ " RE-OPEN TITLE")
	tmp_title.set(m["title"])
	f_title = remove_illegal(m["title"])
	filename.set("#{directory}/" ^ folder() ^  "/#{f_title}." ^ ext() ^ ".rec#" ^ string(counter()))
	nowrecording.set("[#{f_title}." ^ ext() ^ ".rec#" ^ string(counter()) ^ "]")
	log(label="liquidsoap-record", level=2,"#" ^ string(counter()) ^ " New Track Detected. Recording.. #{f_title}." ^ ext())	
	log(label="liquidsoap-record", level=2,"-- press CTRL-C to stop/exit --")
	true	
	else
	log(label="liquidsoap-record", level=3,"#" ^ string(counter()) ^ " FALSE - NOT RE-OPENING" )
	false
	end
end

def post_handle_file(f)
	f_duration = request.duration(resolve_metadata=false,f)
	let (t,n) = string.split.first(separator=".rec", f)	
	tfilename.set(t)
	log(label="liquidsoap-record", level=3,n ^ " POST DURATION " ^ string(f_duration))
	log(label="liquidsoap-record", level=3,n ^ " CLOSE " ^ string(f_duration) ^ " [" ^ format_time(float_of_string(string(f_duration))) ^ "]  " ^ f )
	
	if file.exists(tfilename()) then
	tfilename.set(time.string(tfilename() ^ "-%Y-%m-%d_%H-%M-%S." ^ ext()))
	end
	
	if (f_duration < 15.) and (keep == "0") then
	file.remove(f)
	log(label="liquidsoap-record", level=3,n ^ " Deleted unwanted fragment " ^ tfilename())
	
	elsif (f_duration < 15.)and (keep == "1") then
	file.copy(f,tfilename())
	file.mkdir("#{directory}/" ^ folder() ^ "/incomplete")
	file.move(t,"#{directory}/" ^ folder() ^ "/incomplete")
	file.remove(f)
	log(label="liquidsoap-record", level=3,n ^ " Moved unwanted fragment ID " ^ n ^ " to incomplete.Filename "  ^ tfilename())
		
	elsif (f_duration > 15.) then
	file.copy(f,tfilename())
	file.remove(f)
	log(label="liquidsoap-record", level=3,n ^ " Finished. Saved filename : " ^ tfilename())
	
	end
end

#file/fragments handling on close
def handle_file(f)
	let (t,n) = string.split.first(separator=".rec", f)
	log(label="liquidsoap-record", level=3,n ^ " ORIGINAL DURATION " ^  string(request.duration(resolve_metadata=false,f)))
	tfilename.set(t)
	if codec_name() == "flac" then
	log(label="liquidsoap-record", level=3,n ^ " FFMPEG-reprocess (FLAC) " ^ f)
	tmp_filename = f ^ ".tmp"
	tmp_flac_filename = f ^ ".flac"
	file.copy(f,tmp_filename)
	process.run("ffmpeg -y -i " ^ string.quote(tmp_filename) ^ " " ^  string.quote(tmp_flac_filename)) 
	file.remove(f)
	file.copy(tmp_flac_filename,f)
	file.remove(tmp_filename)
	file.remove(tmp_flac_filename)
	post_handle_file(f)
	else
	log(label="liquidsoap-record", level=3,n ^ " FFMPEG-reprocess (OTHER) " ^ f)
	tmp_filename = f ^ ".tmp"
	tmp_ext_filename = f ^ "." ^ ext()
	file.copy(f,tmp_filename)
	process.run("ffmpeg -y -i " ^ string.quote(tmp_filename) ^ " -c:a copy " ^  string.quote(tmp_ext_filename)) 
	file.remove(f)
	file.copy(tmp_ext_filename,f)
	file.remove(tmp_filename)
	file.remove(tmp_ext_filename)
	post_handle_file(f)
	end
end



#stream copy file writer

if transcode == "0" then
log(label="liquidsoap-record", level=2,"STREAM COPY MODE")
log(label="liquidsoap-record", level=2,"Recording.. " ^ filename())	
log(label="liquidsoap-record", level=2,"--press CTRL-C to stop/exit.")

#default streamcopy mode - audio.copy

s1 = input.ffmpeg(self_sync=true,url()) 


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
  
#output to portaudio (use ffmpeg.decode.audio(s1))  
%ifdef output.portaudio
if (listen == "1") and (device == "portaudio") then
x = output.portaudio(mksafe(ffmpeg.decode.audio(s1)))
end  
%endif

#output to alsa (use ffmpeg.decode.audio(s1))  
%ifdef output.alsa
if (listen == "1") and (device == "alsa") then
x = output.alsa(mksafe(ffmpeg.decode.audio(s1)))
end  
%endif

#progess logging  
thread.run(every=30.,fun() -> log(label="liquidsoap-record", level=2,"Recorded " ^ format_time(s1.elapsed()) ^ " " ^ nowrecording()))

else

#stream transcoding file writer
log(label="liquidsoap-record", level=2,"STREAM TRANSCODING MODE")
log(label="liquidsoap-record", level=2,"Recording.. " ^ filename())	
log(label="liquidsoap-record", level=2,"--press CTRL-C to stop/exit.")

s2 = input.ffmpeg(self_sync=true,url()) 


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
%ifdef output.portaudio
if (listen == "1") and (device == "portaudio") then
x = output.portaudio(mksafe(s2))
end  
%endif

#output to alsa (use s2 pcm) 
%ifdef output.alsa
if (listen == "1") and (device == "alsa") then
x = output.alsa(mksafe(s2))
end  
%endif


#progess logging  
thread.run(every=30.,fun() -> log(label="liquidsoap-record", level=2,"Recorded " ^ format_time(s2.elapsed()) ^ " " ^ nowrecording() ))

end
