param(
  [int]$ApiPort = 8787
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\.."
Set-Location $root

Write-Host "== Python syntax =="
& ".\.venv\Scripts\python.exe" -m compileall -q server.py run.py check_env.py pipelines tests

Write-Host "== Unit tests =="
& ".\.venv\Scripts\python.exe" -m unittest discover -s tests -v

Write-Host "== Environment check =="
& ".\.venv\Scripts\python.exe" run.py check

Write-Host "== API health =="
try {
  $health = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/api/health" -TimeoutSec 5
  $health | ConvertTo-Json -Depth 6
} catch {
  Write-Warning "API not running on $ApiPort; start with: py run.py serve --no-open --port $ApiPort"
}

Write-Host "== Dashboard parse =="
$node = "C:\Program Files\nodejs\node.exe"
if (Test-Path $node) {
  & $node -e "const fs=require('fs'); for (const p of ['dashboard/index.html','dashboard/bta-site/index.html']) { const html=fs.readFileSync(p,'utf8'); const m=html.match(/<script>([\s\S]*?)<\/script>/); new Function(m[1]); console.log(p+' parses'); }"
} else {
  Write-Warning "Node not found; skipped dashboard JS parse."
}
