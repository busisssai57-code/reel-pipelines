# Comprehensive QA Test Suite for Reel Studio
$baseUrl = "http://127.0.0.1:8787"
$results = @()

function Test-Endpoint {
    param([string]$method, [string]$endpoint, [string]$description)
    try {
        $url = "$baseUrl$endpoint"
        if ($method -eq "GET") {
            $response = Invoke-WebRequest -Uri $url -Method GET -ErrorAction Stop
            $results += @{
                Endpoint = $endpoint
                Method = $method
                Status = "✓ PASS"
                Code = $response.StatusCode
                Description = $description
            }
            return $response.Content
        }
        elseif ($method -eq "POST") {
            $body = @{ topic = "Test Topic"; visual_source = "auto" } | ConvertTo-Json
            $response = Invoke-WebRequest -Uri $url -Method POST -Body $body -ContentType "application/json" -ErrorAction Stop
            $results += @{
                Endpoint = $endpoint
                Method = $method
                Status = "✓ PASS"
                Code = $response.StatusCode
                Description = $description
            }
            return $response.Content
        }
    } catch {
        $results += @{
            Endpoint = $endpoint
            Method = $method
            Status = "✗ FAIL"
            Code = $_.Exception.Response.StatusCode
            Error = $_.Exception.Message
            Description = $description
        }
    }
}

Write-Host "`n=== REEL STUDIO QA TEST SUITE ===" -ForegroundColor Cyan
Write-Host "Testing all API endpoints and features...`n"

# Test Dashboard Access
Write-Host "[1/12] Testing Dashboard Access..." -ForegroundColor Yellow
Test-Endpoint -Method GET -Endpoint "/" -Description "Dashboard HTML"

# Test Agent Status
Write-Host "[2/12] Testing Agent Status Endpoint..." -ForegroundColor Yellow
Test-Endpoint -Method GET -Endpoint "/api/agents" -Description "Get all agents"

# Test Trends
Write-Host "[3/12] Testing Trends Endpoint..." -ForegroundColor Yellow
Test-Endpoint -Method GET -Endpoint "/api/trends" -Description "Get trending topics"

# Test Engagement
Write-Host "[4/12] Testing Engagement Endpoint..." -ForegroundColor Yellow
Test-Endpoint -Method GET -Endpoint "/api/engagement" -Description "Get engagement metrics"

# Test Patches
Write-Host "[5/12] Testing Code Patches Endpoint..." -ForegroundColor Yellow
Test-Endpoint -Method GET -Endpoint "/api/patches" -Description "Get code patches"

# Test Drafts
Write-Host "[6/12] Testing Drafts Endpoint..." -ForegroundColor Yellow
Test-Endpoint -Method GET -Endpoint "/api/drafts" -Description "Get all drafts"

# Test Render
Write-Host "[7/12] Testing Render Endpoint..." -ForegroundColor Yellow
Test-Endpoint -Method POST -Endpoint "/api/render" -Description "Start render job"

# Test Agents Info
Write-Host "[8/12] Testing Agent Details..." -ForegroundColor Yellow
Test-Endpoint -Method GET -Endpoint "/api/agents/status" -Description "Get agent health details"

Write-Host "`n=== TEST RESULTS ===" -ForegroundColor Cyan
$passed = ($results | Where-Object { $_.Status -like "*PASS*" }).Count
$failed = ($results | Where-Object { $_.Status -like "*FAIL*" }).Count
Write-Host "Passed: $passed | Failed: $failed" -ForegroundColor Green

foreach ($result in $results) {
    if ($result.Status -like "*PASS*") {
        Write-Host "✓ $($result.Method) $($result.Endpoint) - $($result.Description)" -ForegroundColor Green
    } else {
        Write-Host "✗ $($result.Method) $($result.Endpoint) - ERROR: $($result.Error)" -ForegroundColor Red
    }
}

$results | ConvertTo-Json | Out-File "D:\reel-pipelines\QA_RESULTS.json"
Write-Host "`n✓ Results saved to QA_RESULTS.json"
