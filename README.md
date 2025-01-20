
# liquidsoap-record

Record internet radio streams (aac,mp3,flac,opus,vorbis) with liquidsoap. 


## Requirements
OS : tested with Windows10 and Debian(bookworm)

liquidsoap 2.2.5 , 2.3.0

https://github.com/savonet/liquidsoap/releases

ffprobe & ffmpeg 

windows : https://www.gyan.dev/ffmpeg/builds/ 
linux : sudo apt install ffmpeg


## command

```
 liquidsoap record.liq -- -url "url" -dir "directory" -transcode "0" -samplerate "samplerate" -format "format" -codec "codec" -bitrate "bitrate" -listen "0" -device "portaudio|alsa" -log "2" -keep "0" -id "tunein_id" -relay "0" -host "host" -port "port" -password "password" 
```



| argument      | description |
| ------------- | ------------- |
| -url          | listen url |
| -dir          | directory to save files |
| -transcode         | transcode : 0 = no (default) , 1 = yes|
| -samplerate         | encoder samplerate|
| -format          | encoder container format |
| -codec       | encoder codec  |
| -bitrate          | encoder bitrate |
| -listen         | listen to output : 0 = no (default) , 1 = yes |
| -device         | listen to output with device : portaudio (default) , alsa |
| -log       | log level : 1 crtitcal , 2 severe (default) , 3 important, 4 info , 5 debug|
| -keep         | keep fragments & move them to "incomplete" subfolder : 0 = no (default) , 1 = yes |
| -id         | tunein id |
| -relay         | relay output to icecast server: 0 = no (default) , 1 = yes |
| -host         | icecast host |
| -port         | icecast port |
| -password         | icecast password |


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
liquidsoap record.liq -- -url "http://stream.radiojar.com/aay95tkmb" -dir "c:\music" -id s240638
```

## Transcoding

Transcoding suggestions table

| format     | arguments|
| ------------- | ------------- |
| OPUS          | -samplerate 48000 -format opus -codec libopus -bitrate 128k|
| MP3         | -samplerate 44100 -format mp3 -codec libmp3lame -bitrate 320k |
| AAC        | -samplerate 44100 -format m4a -codec aac -bitrate 320k|
| FLAC        | -samplerate 44100 -format flac -codec flac|


## Known Issues

HLS in mp4 format doesn't return metadata.
(ffmpeg - Changing ID3 metadata in HLS audio elementary stream is not implemented.)

