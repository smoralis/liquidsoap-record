Record streams with liquidsoap. 

Reuirements:

liquidsoap

https://github.com/savonet/liquidsoap/releases

ffprobe

https://www.gyan.dev/ffmpeg/builds/


#windows command 

liquidsoap.exe record.liq -- -url "url" -dir "directory" -t "0" -samplerate "samplerate" -format "format" -codec "codec" -bitrate "bitrate" -l "0" -log "2"


Arguments:

-url url

-dir directory to save files

-t transcode  0 = no (default) 1 = yes

-samplerate encoder samplerate

-format encoder container format

-codec encoder codec 

-bitrate encoder bitrate

-l listen with portaudio 0 = no (default)  1 = yes

-log log level 2 (default) 


e.g

Stream copy

liquidsoap.exe record.liq -- -url "http://ice1.somafm.com/groovesalad-256-mp3" -dir "c:\music"

Transcoding

liquidsoap.exe record.liq -- -url "https://stream.radioparadise.com/rock-flacm" -dir "c:\music" -t 1 -samplerate 48000 -format opus -codec libopus -bitrate 128k


Transcoding suggestions table

OPUS 
-samplerate 48000
-format opus
-codec libopus
-bitrate 128k

MP3 
-samplerate 44100
-format mp3
-codec libmp3lame
-bitrate 320k

AAC 
-samplerate 44100
-format m4a
-codec aac
-bitrate 320k

FLAC
-samplerate 44100
-format flac
-codec flac


Changelog:

1.0.7
fix: ffprobe codec detection (json)
add: log level selection
add: delete incomplete recording fragments

1.0.6
add: create listen.m3u 

1.0.5
add: ffprobe icy-name as folder name (if availiable)

1.0.4
add: stream copy mode

1.0.3
fix: url strip after ?

1.0.2
fix: ignore received duplicate metadata 

1.0.1
fix: strip text after | from %title%

1.0.0
Initial release
