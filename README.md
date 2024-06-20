Record streams with liquidsoap. 

https://github.com/savonet/liquidsoap/releases

#windows command 
liquidsoap.exe record.liq -- "<url>" "<directory>" "<format>" "<codec>"

e.g
liquidsoap.exe record.liq -- "https://stream.url" "c:\music" flac flac

liquidsoap.exe record.liq -- "https://stream.url" "c:\music" mp3 libmp3lame
