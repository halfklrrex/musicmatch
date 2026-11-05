# MusicMatch

Small Windows app that turns YouTube links into MP3 or MP4 files.

- Paste links to single songs (playlist and mix links are ignored, so one pasted song is one queue row); each becomes a queue row with its own MP3/MP4 toggle
- English and Spanish interface (EN / ES switch in the top bar)
- MP3: 128/192/320 kbps with cover art and title/artist tags. MP4: H.264 + AAC, Best/1080/720/480/360
- Clean song tags and file names for car stereos and players: "Artist - Song (Official Video)" becomes title "Song", artist "Artist" and the file `Song - Artist.mp3` (ID3v2.3 + ID3v1, cover art kept). Both fields can be edited before downloading
- Optional trim (start/end) and volume normalize per item (on by default)
- Clipboard detection (and Ctrl+V anywhere), thumbnails and durations, download history
- 1 to 4 parallel downloads, and an "Update yt-dlp" button for when YouTube changes

Interface: HTML/CSS in an Edge WebView2 window (pywebview), Poppins font. Engine: Python, yt-dlp, ffmpeg.

## Run from source
```powershell
pip install -r requirements.txt
pwsh scripts\fetch_binaries.ps1   # one-time: yt-dlp, ffmpeg, deno into .\bin
python run.py                     # set MM_DEBUG=1 to open the web inspector
```
Needs the Microsoft Edge WebView2 Runtime (included with Windows 11 and current Windows 10).

## Build the .exe
```powershell
pwsh scripts\build.ps1            # -> dist\MusicMatch.exe
```

## Layout
- `musicmatch/webui/`: the interface (`index.html`, `styles.css`, `app.js`, fonts, icon)
- `musicmatch/api.py`: bridge the interface calls into; pushes progress events back
- `musicmatch/downloader.py`, `metadata.py`: yt-dlp / ffmpeg engine
- `assets/`: Twin Arch logo (SVG) and app icon

Settings and history live in `%APPDATA%\MusicMatch`; the updatable yt-dlp copy in `%LOCALAPPDATA%\MusicMatch\bin`.
Default output folder: `Downloads\MusicMatch`.

Only download content you have the right to download.

## Credits
Interface font: [Poppins](https://github.com/itfoundry/Poppins), SIL Open Font License 1.1 (see `musicmatch/webui/fonts/OFL.txt`).
