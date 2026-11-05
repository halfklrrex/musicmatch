# Downloads yt-dlp, ffmpeg/ffprobe and deno into ..\bin
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path $PSScriptRoot -Parent
$bin = Join-Path $root 'bin'
$tmp = Join-Path $env:TEMP 'musicmatch_fetch'
New-Item -ItemType Directory -Force $bin, $tmp | Out-Null

Write-Host 'yt-dlp...'
Invoke-WebRequest 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe' -OutFile (Join-Path $bin 'yt-dlp.exe')

Write-Host 'ffmpeg...'
$ff = Join-Path $tmp 'ffmpeg.zip'
Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $ff
$ffx = Join-Path $tmp 'ffmpeg'
if (Test-Path $ffx) { Remove-Item $ffx -Recurse -Force }
Expand-Archive $ff $ffx
Get-ChildItem $ffx -Recurse -Include ffmpeg.exe, ffprobe.exe | Copy-Item -Destination $bin -Force

Write-Host 'deno...'
$dn = Join-Path $tmp 'deno.zip'
Invoke-WebRequest 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip' -OutFile $dn
Expand-Archive $dn $bin -Force

Remove-Item $tmp -Recurse -Force
Get-ChildItem $bin | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
