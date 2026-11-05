# Builds dist\MusicMatch.exe (one file, bundles yt-dlp/ffmpeg/deno from .\bin)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

if (-not (Test-Path 'bin\ffmpeg.exe')) { & "$PSScriptRoot\fetch_binaries.ps1" }

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name MusicMatch `
    --collect-all customtkinter `
    --add-data "bin;bin" `
    --add-data "musicmatch/assets;musicmatch/assets" `
    run.py

Get-Item dist\MusicMatch.exe | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
