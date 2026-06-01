#!/usr/bin/env pwsh
<#
.SYNOPSIS
Interactive .env setup for reel-pipelines.

.DESCRIPTION
Prompts for each required configuration key and writes a .env file.
Supports prefilling from an existing .env if present.

.EXAMPLE
PS> .\scripts\setup-env.ps1
#>

param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$EnvFile = Join-Path $Root ".env"

Write-Host "=== Reel Pipelines Environment Setup ===" -ForegroundColor Cyan
Write-Host

# Try to load existing values
$Existing = @{}
if (Test-Path $EnvFile) {
    Write-Host "Loading existing .env values as defaults..." -ForegroundColor Yellow
    foreach ($Line in (Get-Content $EnvFile)) {
        if ($Line -match "^([A-Z_]+)=(.*)$") {
            $Key, $Value = $Matches[1], $Matches[2]
            $Existing[$Key] = $Value -replace '^["\']|["\']$', ''
        }
    }
}

$Settings = [ordered]@{
    "OPENAI_API_KEY" = "Local Qwen endpoint auth (usually 'ollama')"
    "OPENAI_API_BASE" = "Local Qwen endpoint URL (usually http://localhost:11434/v1)"
    "PEXELS_KEY" = "Pexels video API key (free from pexels.com/api)"
    "PIXABAY_KEY" = "Pixabay media API key (free from pixabay.com/api)"
    "DISCORD_BOT_TOKEN" = "Discord bot token for approval loop"
    "DISCORD_CHANNEL_ID" = "Discord channel ID for reel approval (numeric)"
    "COMFY_URL" = "ComfyUI server URL (usually http://127.0.0.1:8188)"
    "COMFY_OUTPUT" = "ComfyUI output directory (usually D:\ComfyUI\output)"
    "FFMPEG_BIN" = "FFmpeg binary path (or leave blank if on PATH)"
    "FFPROBE_BIN" = "FFprobe binary path (or leave blank if on PATH)"
    "REEL_API_KEY" = "API key for accessing render endpoints"
    "AUTOPOST_MODE" = "Publishing mode: 'local_manifest' or 'webhook'"
}

$Env = @{}

foreach ($Key in $Settings.Keys) {
    $Desc = $Settings[$Key]
    $Default = $Existing[$Key] ?? ""
    $Prompt = "$Key"
    if ($Default) {
        $Prompt += " [$Default]"
    }
    $Prompt += ": "
    $Input = Read-Host $Prompt
    $Env[$Key] = if ($Input) { $Input } else { $Default }
}

Write-Host
Write-Host "Writing .env..." -ForegroundColor Green
$EnvContent = $Env.GetEnumerator() |
    ForEach-Object { "$($_.Key)=$($_.Value)" } |
    Join-String -Separator "`n"
Set-Content -Path $EnvFile -Value $EnvContent -Encoding UTF8

Write-Host "✓ .env written to $EnvFile" -ForegroundColor Green
Write-Host

# Run check_env
Write-Host "Running environment check..." -ForegroundColor Cyan
Push-Location $Root
& py run.py check
Pop-Location
