param(
  [string]$ComfyRoot = "D:\ComfyUI",
  [int]$Port = 8188,
  [switch]$Listen
)

$ErrorActionPreference = "Stop"
$python = Join-Path $ComfyRoot ".venv\Scripts\python.exe"
$main = Join-Path $ComfyRoot "main.py"
if (-not (Test-Path $python) -or -not (Test-Path $main)) {
  throw "ComfyUI is not installed at $ComfyRoot. Run .\scripts\install-hunyuan.ps1 first."
}

$args = @($main, "--port", $Port)
if ($Listen) { $args += @("--listen", "0.0.0.0") }
if ((Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match "NVIDIA" })) {
  $args += "--use-sage-attention"
}

Write-Host "Starting ComfyUI/Hunyuan backend on http://127.0.0.1:$Port"
& $python @args
