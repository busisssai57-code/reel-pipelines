param(
  [string]$InstallRoot = "D:\reel-pipelines\tools\ffmpeg"
)

$ErrorActionPreference = "Stop"
$zip = Join-Path $env:TEMP "ffmpeg-release-essentials.zip"
$url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Write-Host "Downloading FFmpeg essentials from $url"
Invoke-WebRequest -Uri $url -OutFile $zip

$tmp = Join-Path $env:TEMP ("ffmpeg-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
$bin = Get-ChildItem -Path $tmp -Recurse -Directory -Filter "bin" | Select-Object -First 1
if (-not $bin) { throw "Could not find bin directory in FFmpeg archive." }
Copy-Item -Path (Join-Path $bin.FullName "*") -Destination $InstallRoot -Recurse -Force
Remove-Item $tmp -Recurse -Force

Write-Host "FFmpeg installed:"
& (Join-Path $InstallRoot "ffmpeg.exe") -version | Select-Object -First 1
Write-Host "Set in .env:"
Write-Host "FFMPEG_BIN=$InstallRoot\ffmpeg.exe"
Write-Host "FFPROBE_BIN=$InstallRoot\ffprobe.exe"
