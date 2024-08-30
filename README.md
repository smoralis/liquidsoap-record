
# liquidsoap-record

Record internet radio streams (aac,mp3,flac,opus,vorbis) with liquidsoap. 


## Requirements
OS : tested with Windows10 and Debian(bookworm)

liquidsoap >=2.2.5

https://github.com/savonet/liquidsoap/releases

ffprobe & ffmpeg 

windows : https://www.gyan.dev/ffmpeg/builds/ 
linux : sudo apt install ffmpeg


## command

```
 liquidsoap record.liq -- -url "url" -dir "directory" -transcode "0" -samplerate "samplerate" -format "format" -codec "codec" -bitrate "bitrate" -listen "0" -device "portaudio|alsa" -log "2" -keep "0"
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


## Examples

Stream Copy
```
liquidsoap record.liq -- -url "http://ice1.somafm.com/groovesalad-256-mp3" -dir "c:\music"
```

Transcoding
```
liquidsoap record.liq -- -url "https://stream.radioparadise.com/rock-flacm" -dir "c:\music" -transcode 1 -samplerate 48000 -format opus -codec libopus -bitrate 128k

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

