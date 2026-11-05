# MusicMatch

Small Windows app that turns YouTube links into MP3 or MP4 files.

- Queue of URLs (playlists expand into one row per video), each row with its own MP3/MP4 toggle
- MP3: 128/192/320 kbps, cover art + title/artist tags. MP4: H.264 + AAC, Best/1080/720/480/360
- Optional trim (start/end) and volume normalize per item
- Clipboard detection, thumbnails/durations, download history, remembered settings
- 1-4 parallel downloads, "Update yt-dlp" button for when YouTube changes

## Run from source
```powershell
pip install -r requirements.txt
pwsh scripts\fetch_binaries.ps1   # one-time: yt-dlp, ffmpeg, deno into .\bin
python run.py
```

## Build the .exe
```powershell
pwsh scripts\build.ps1            # -> dist\MusicMatch.exe
```

Settings and history live in `%APPDATA%\MusicMatch`; the updatable yt-dlp copy in `%LOCALAPPDATA%\MusicMatch\bin`.
Default output folder: `Downloads\MusicMatch`.

Only download content you have the right to download.

## Credits
Interface font: [Poppins](https://github.com/itfoundry/Poppins), SIL Open Font License 1.1 (see `musicmatch/assets/fonts/OFL.txt`).
