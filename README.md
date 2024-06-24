Record streams with liquidsoap. 

Reuirements:
liquidsoap
https://github.com/savonet/liquidsoap/releases

ffprobe
https://www.gyan.dev/ffmpeg/builds/


#windows command 

liquidsoap.exe record.liq -- -url "<url>" -dir "<directory>" -t <0> -samplerate "<samplerate>" -format "<format>" -codec "<codec>" -bitrate "<bitrate>" -l <0>

-url url
-dir directory to save files

-t transcode  0 = no (default) 1 = yes
-samplerate encoder samplerate
-format encoder container format
-codec encoder codec 
-bitrate encoder bitrate

-l listen with portaudio 0 = no (default)  1 = yes


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
