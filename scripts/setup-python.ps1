param(
  [string]$Python = "py -3.11",
  [switch]$Recreate
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

if ($Recreate -and (Test-Path ".venv")) {
  Remove-Item ".venv" -Recurse -Force
}

if (-not (Test-Path ".venv")) {
  & py -3.11 -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip wheel setuptools
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\.venv\Scripts\python.exe" -m unittest discover -s tests -v
