param(
  [string]$ComfyRoot = "D:\ComfyUI",
  [switch]$DownloadModels,
  [switch]$Force
)

$ErrorActionPreference = "Stop"

function Invoke-Step($Name, [scriptblock]$Block) {
  Write-Host "`n==> $Name" -ForegroundColor Cyan
  & $Block
}

function Ensure-Command($Name, $InstallHint) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "$Name was not found. $InstallHint"
  }
}

$ComfyRoot = [System.IO.Path]::GetFullPath($ComfyRoot)
$customNodes = Join-Path $ComfyRoot "custom_nodes"
$models = Join-Path $ComfyRoot "models"

Ensure-Command git "Install Git for Windows: https://git-scm.com/download/win"
Ensure-Command py "Install Python 3.10 or 3.11 from python.org."

Invoke-Step "Clone or update ComfyUI" {
  if (Test-Path $ComfyRoot) {
    if ($Force) { git -C $ComfyRoot pull --ff-only }
  } else {
    git clone --depth 1 --filter=blob:none https://github.com/comfyanonymous/ComfyUI.git $ComfyRoot
  }
}

Invoke-Step "Create ComfyUI virtual environment" {
  if (-not (Test-Path (Join-Path $ComfyRoot ".venv"))) {
    py -3.11 -m venv (Join-Path $ComfyRoot ".venv")
  }
  $python = Join-Path $ComfyRoot ".venv\Scripts\python.exe"
  & $python -m pip install --upgrade pip wheel setuptools
  & $python -m pip install -r (Join-Path $ComfyRoot "requirements.txt")
}

Invoke-Step "Install production video custom nodes" {
  New-Item -ItemType Directory -Force -Path $customNodes | Out-Null
  $nodes = @(
    @{Name="ComfyUI-Manager"; Url="https://github.com/ltdrdata/ComfyUI-Manager.git"},
    @{Name="ComfyUI-VideoHelperSuite"; Url="https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git"},
    @{Name="ComfyUI-KJNodes"; Url="https://github.com/kijai/ComfyUI-KJNodes.git"},
    @{Name="ComfyUI-HunyuanVideoWrapper"; Url="https://github.com/kijai/ComfyUI-HunyuanVideoWrapper.git"},
    @{Name="ComfyUI-LatentSyncWrapper"; Url="https://github.com/ShmuelRonen/ComfyUI-LatentSyncWrapper.git"}
  )
  foreach ($node in $nodes) {
    $dest = Join-Path $customNodes $node.Name
    if (Test-Path $dest) {
      if ($Force) { git -C $dest pull --ff-only }
    } else {
      git clone --depth 1 --filter=blob:none $node.Url $dest
    }
    $req = Join-Path $dest "requirements.txt"
    if (Test-Path $req) {
      & (Join-Path $ComfyRoot ".venv\Scripts\python.exe") -m pip install -r $req
    }
  }
}

Invoke-Step "Create model directories" {
  "diffusion_models","text_encoders","vae","clip_vision","checkpoints" | ForEach-Object {
    New-Item -ItemType Directory -Force -Path (Join-Path $models $_) | Out-Null
  }
}

if ($DownloadModels) {
  Invoke-Step "Download Hunyuan Video model weights" {
    $python = Join-Path $ComfyRoot ".venv\Scripts\python.exe"
    $env:HF_HUB_DISABLE_XET = "1"
    & $python -m pip install --upgrade "huggingface_hub[cli]"
    function Download-HfFile($RepoPath, $DestSubdir, [Int64]$MinBytes) {
      $leaf = Split-Path $RepoPath -Leaf
      $destDir = Join-Path $models $DestSubdir
      $dest = Join-Path $destDir $leaf
      if (Test-Path $dest) {
        $size = (Get-Item $dest).Length
        if ($size -ge $MinBytes) {
          Write-Host "Already present: $dest"
          return
        }
        Write-Host "Resuming incomplete file: $dest ($size bytes)"
      }
      $urlPath = $RepoPath -replace "\\", "/"
      $url = "https://huggingface.co/Comfy-Org/HunyuanVideo_repackaged/resolve/main/$urlPath`?download=true"
      $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
      if ($curl) {
        & $curl.Source -L --fail --retry 20 --retry-delay 5 -C - -o $dest $url
      } else {
        & $python -c "from huggingface_hub import hf_hub_download; import pathlib, shutil, sys; src=hf_hub_download('Comfy-Org/HunyuanVideo_repackaged', sys.argv[1]); dst=pathlib.Path(sys.argv[2]); dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(src, dst); print(dst)" $RepoPath $dest
      }
      if (-not (Test-Path $dest)) { throw "Download finished but file was not found: $dest" }
    }
    Download-HfFile "split_files/diffusion_models/hunyuan_video_t2v_720p_bf16.safetensors" "diffusion_models" 25000000000
    Download-HfFile "split_files/text_encoders/clip_l.safetensors" "text_encoders" 200000000
    Download-HfFile "split_files/text_encoders/llava_llama3_fp8_scaled.safetensors" "text_encoders" 8500000000
    Download-HfFile "split_files/vae/hunyuan_video_vae_bf16.safetensors" "vae" 400000000
  }
} else {
  Write-Host "`nModel download skipped. Re-run with -DownloadModels to fetch ~36GB of Hunyuan weights." -ForegroundColor Yellow
}

Write-Host "`nHunyuan/ComfyUI install prepared at $ComfyRoot" -ForegroundColor Green
Write-Host "Start it with: .\scripts\start-comfy.ps1 -ComfyRoot `"$ComfyRoot`"" -ForegroundColor Green
