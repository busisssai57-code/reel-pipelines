#Requires -Version 5.0
<#
.SYNOPSIS
Interactive OAuth setup for YouTube and TikTok platform integration.

.DESCRIPTION
Guides user through YouTube and TikTok OAuth flows to store access tokens
in the state.db database for autonomous distribution.

.EXAMPLE
.\setup-oauth.ps1
.\setup-oauth.ps1 -Platform youtube
#>
param(
    [ValidateSet('youtube', 'tiktok', $null)]
    [string]$Platform
)

$ROOT = Split-Path (Split-Path $PSScriptRoot)

function Write-Header {
    Write-Host "`n=== $args ===`n" -ForegroundColor Cyan
}

function Write-Info {
    Write-Host "[INFO] $args" -ForegroundColor Green
}

function Write-Error-Custom {
    Write-Host "[ERROR] $args" -ForegroundColor Red
}

function Setup-YouTube {
    Write-Header "YouTube OAuth Setup"

    Write-Host @"
This will register your YouTube channel for autonomous publishing.

You'll need:
1. Google Cloud Console: https://console.cloud.google.com
2. OAuth 2.0 credentials (Desktop application)
3. YouTube Data API v3 enabled

Steps:
1. Create a project in Google Cloud Console
2. Enable YouTube Data API v3
3. Create OAuth 2.0 credentials (Desktop)
4. Copy Client ID and Client Secret

"@ -ForegroundColor Yellow

    $clientId = Read-Host "Enter YouTube Client ID"
    $clientSecret = Read-Host "Enter YouTube Client Secret (will be hidden)" -AsSecureString
    $clientSecretPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToCoTaskMemUnicode($clientSecret))

    $channelId = Read-Host "Enter YouTube Channel ID (from youtube.com/@yourhandle/about)"

    # Open browser for OAuth consent
    $authUrl = "https://accounts.google.com/o/oauth2/v2/auth?client_id=$clientId&redirect_uri=http://localhost:8888/callback&response_type=code&scope=https://www.googleapis.com/auth/youtube.upload"

    Write-Info "Opening browser for YouTube OAuth consent..."
    Start-Process $authUrl

    Write-Host @"
1. Click 'Consent' in the browser
2. You'll be redirected to localhost:8888/callback?code=...
3. Copy the 'code' parameter value from the URL
"@ -ForegroundColor Yellow

    $authCode = Read-Host "Paste the authorization code from the redirect URL"

    # Exchange code for tokens (simplified, requires HTTP server or manual token fetch)
    Write-Info "Token exchange - this requires manual setup via Google OAuth tools"
    Write-Host @"
For now, you'll need to manually get the access token:
1. Go to: https://www.googleapis.com/oauth2/v4/token
2. POST with:
   - grant_type: authorization_code
   - code: $authCode
   - client_id: $clientId
   - client_secret: $clientSecretPlain
   - redirect_uri: http://localhost:8888/callback

3. The response will include 'access_token' and 'refresh_token'
4. Come back and paste them below
"@ -ForegroundColor Yellow

    $accessToken = Read-Host "Enter access_token"
    $refreshToken = Read-Host "Enter refresh_token"

    # Store in database
    Write-Info "Saving YouTube credentials to database..."
    $pythonCode = @"
import sys
sys.path.insert(0, r'$ROOT')
from pipelines.common import db, config
db.init()
import time
expires_at = time.time() + 3600  # 1 hour from now
db.set_platform_token(
    'youtube',
    '$accessToken',
    '$refreshToken',
    expires_at,
    'https://www.googleapis.com/auth/youtube.upload'
)
print('YouTube token saved!')
"@

    py -c $pythonCode
    Write-Info "YouTube OAuth setup complete! ✓"
}

function Setup-TikTok {
    Write-Header "TikTok OAuth Setup"

    Write-Host @"
This will register for TikTok Content Posting API.

You'll need:
1. TikTok for Developers: https://developers.tiktok.com
2. An approved content posting app
3. Client key and secret

Steps:
1. Create app in TikTok Developer Console
2. Request 'Video Posting' permission
3. Copy Client Key and Client Secret
4. Get your OAuth credential refresh_token

"@ -ForegroundColor Yellow

    $clientKey = Read-Host "Enter TikTok Client Key"
    $clientSecret = Read-Host "Enter TikTok Client Secret (will be hidden)" -AsSecureString
    $clientSecretPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToCoTaskMemUnicode($clientSecret))

    # TikTok OAuth flow is more complex; simplified for manual token input
    Write-Host @"
TikTok OAuth requires additional manual steps:
1. Go to: https://www.tiktok.com/oauth/authorize
2. Use Client Key: $clientKey
3. Authorize your app
4. You'll receive a refresh_token

Paste the refresh_token below (or access_token if you have it).
"@ -ForegroundColor Yellow

    $accessToken = Read-Host "Enter access_token (or temporary token)"
    $refreshToken = Read-Host "Enter refresh_token"

    # Store in database
    Write-Info "Saving TikTok credentials to database..."
    $pythonCode = @"
import sys
sys.path.insert(0, r'$ROOT')
from pipelines.common import db, config
db.init()
import time
expires_at = time.time() + 14400  # 4 hours from now
db.set_platform_token(
    'tiktok',
    '$accessToken',
    '$refreshToken',
    expires_at,
    'video.upload,video.publish'
)
print('TikTok token saved!')
"@

    py -c $pythonCode
    Write-Info "TikTok OAuth setup complete! ✓"
}

# Main
if (-not $Platform -or $Platform -eq 'youtube') {
    Setup-YouTube
}

if (-not $Platform -or $Platform -eq 'tiktok') {
    Setup-TikTok
}

Write-Host @"
`n=== Setup Complete ===

Your AI team can now:
✓ Publish to YouTube (via YouTube Data API)
✓ Publish to TikTok (via Content Posting API)
✓ Monitor engagement metrics
✓ Improve content using platform feedback

Next steps:
1. Set AUTO_APPROVE=true in .env for autonomous approvals
2. Set AUTO_PATCH=true for autonomous code patching
3. Run: py run.py ai-team

To test:
  py run.py trend           # Test trend research
  py run.py trend --run     # Run full cycle once
"@ -ForegroundColor Green
