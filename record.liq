#record.liq
#v.1.0.2

#https://github.com/savonet/liquidsoap/releases

#usage liquidsoap.exe record.liq -- "<url>" "<directory>" "<format>" "<codec>"


log.important("Recording.. #{argv(1)}")
log.important("Save Directory.. #{argv(2)}")
log.important("Save Format.. #{argv(3)}")
log.important("Save Codec.. #{argv(4)}")

def remove_illegal(value) =
str = r/[\?\<\>]/g.replace(fun(_) -> "_",value)
str = r/[\*<>]/g.replace(fun(_) -> "x",str)
str = r/[\:\/|\\]/g.replace(fun(_) -> "-",str)
str = r/[\"]/g.replace(fun(_) -> "''",str)
str
end

folder = remove_illegal(argv(1))
directory = "#{argv(2)}"
format = "#{argv(3)}"
codec = "#{argv(4)}"

artist = ref("")
title = ref("")
tmp_artist = ref("")
tmp_title = ref("")

s = input.ffmpeg(argv(1))

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

s = metadata.map(lower_ARTIST, s)
s = metadata.map(lower_TITLE, s)
s = metadata.map(process_metadata, s)

filename = ref(time.string("#{directory}/archive/#{folder}/%Y-%m-%d_%H-%M-%S.#{format}"))

def handle_metadata(m) 
    filename.set(time.string("#{directory}/archive/#{folder}/%Y-%m-%d_%H-%M-%S.#{format}"))
	if (m["artist"] != "") and (m["title"] != "") and (m["artist"] != tmp_artist()) and (m["title"] != tmp_title()) then
	tmp_artist.set(m["artist"])
	tmp_title.set(m["title"])
	f_artist = remove_illegal(m["artist"])
	f_title = remove_illegal(m["title"])
	filename := "#{directory}/archive/#{folder}/#{f_artist} - #{f_title}.#{format}"
	log.important(string(m))
	log.important("New metadata - Starting #{directory}/archive/#{folder}/#{f_artist} - #{f_title}.#{format}")	
	true
	else
	log.important("No metadata or the same metadata - not re-opening output")
	false
	end
end

f = output.file(%ffmpeg(
  format="#{format}",
  %audio(samplerate = 44100, codec = "#{codec}")), 
  filename, 
  s, 
  reopen_on_metadata=handle_metadata, append=true, fallible=true)


#listen - output portaudio
#x = output.portaudio(mksafe(s))