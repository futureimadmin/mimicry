# Mimicry installer for Windows.
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1            (first time)
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Fresh     (rebuild .venv from scratch)
# Options: -CpuOnly (force CPU torch)   -SkipNeural (app only, pitch-only voice)
param([switch]$Fresh, [switch]$CpuOnly, [switch]$SkipNeural)

# pip/git print progress on stderr; with 'Stop' PowerShell 5.1 would treat that as a failure. We check exit codes instead.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force logs | Out-Null
Start-Transcript -Path "logs\install.log" -Force | Out-Null

function Say([string]$m)  { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail([string]$m) { Write-Host "`nFAILED: $m" -ForegroundColor Red; Write-Host "Full log: $(Resolve-Path logs\install.log)"; Stop-Transcript | Out-Null; exit 1 }
function Exec([string]$exe, [string[]]$a) {
  & $exe @a
  if ($LASTEXITCODE -ne 0) { Fail "command failed (exit $LASTEXITCODE): $exe $($a -join ' ')" }
}

# ---- 1. Python 3.10-3.12 ----------------------------------------------------
Say "Looking for Python 3.10 - 3.12"
$py0 = $null
$cands = @()
foreach ($v in "3.11","3.10","3.12") { try { $p = (& py "-$v" -c "import sys;print(sys.executable)" 2>$null); if ($LASTEXITCODE -eq 0 -and $p) { $cands += "$p".Trim() } } catch {} }
foreach ($n in "python","python3") { $c = Get-Command $n -ErrorAction SilentlyContinue; if ($c) { $cands += $c.Source } }
foreach ($c in $cands) {
  try { $ver = "$(& $c -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null)".Trim() } catch { continue }
  if ($ver -in "3.10","3.11","3.12") { $py0 = $c; Write-Host "Using Python $ver at $c"; break }
}
if (-not $py0) { Fail "No Python 3.10/3.11/3.12 found. Install one:  winget install -e --id Python.Python.3.11   (then open a NEW PowerShell and re-run)" }

# ---- 2. virtual environment ---------------------------------------------------
if ($Fresh -and (Test-Path .venv)) { Say "Removing old .venv"; Remove-Item .venv -Recurse -Force }
if ((Test-Path .venv\Scripts\python.exe) -and -not (& .\.venv\Scripts\python.exe -c "import sys" 2>$null; $LASTEXITCODE -eq 0)) { Remove-Item .venv -Recurse -Force }
if (-not (Test-Path .venv\Scripts\python.exe)) { Say "Creating .venv"; Exec $py0 @("-m","venv",".venv") }
$py = (Resolve-Path .venv\Scripts\python.exe).Path

Say "Installing app packages"
Exec $py @("-m","pip","install","--upgrade","pip","setuptools","wheel")
Exec $py @("-m","pip","install","-r","requirements.txt")

# ---- 3. neural voice model ----------------------------------------------------
if (-not $SkipNeural) {
  $gpu = (-not $CpuOnly) -and ($null -ne (Get-Command nvidia-smi -ErrorAction SilentlyContinue))
  if ($gpu) { $idx = "https://download.pytorch.org/whl/cu121"; Say "NVIDIA GPU found - installing PyTorch (CUDA, ~2.5 GB, takes a while)" }
  else      { $idx = "https://download.pytorch.org/whl/cpu";   Say "No NVIDIA GPU - installing PyTorch (CPU)" }
  Exec $py @("-m","pip","install","torch","--index-url",$idx)
  Exec $py @("-m","pip","install","-r","requirements-neural.txt")

  Say "Getting OpenVoice source"
  New-Item -ItemType Directory -Force third_party | Out-Null
  if ((Test-Path third_party\OpenVoice) -and -not (Test-Path third_party\OpenVoice\openvoice\api.py)) { Remove-Item third_party\OpenVoice -Recurse -Force }
  if (-not (Test-Path third_party\OpenVoice\openvoice\api.py)) {
    if (Get-Command git -ErrorAction SilentlyContinue) {
      Exec "git" @("clone","--depth","1","https://github.com/myshell-ai/OpenVoice","third_party\OpenVoice")
    } else {
      $zip = Join-Path $env:TEMP "openvoice-src.zip"; $tmp = Join-Path $env:TEMP "openvoice-src"
      Invoke-WebRequest "https://github.com/myshell-ai/OpenVoice/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
      if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
      Expand-Archive $zip $tmp -Force
      Move-Item (Join-Path $tmp "OpenVoice-main") third_party\OpenVoice
      Remove-Item $zip, $tmp -Recurse -Force
    }
  }
  if (-not (Test-Path third_party\OpenVoice\openvoice\api.py)) { Fail "OpenVoice source is incomplete in third_party\OpenVoice" }

  Say "Downloading the voice model (131 MB) from Hugging Face"
  Exec $py @("scripts\fetch_models.py")

  Say "Self-test: loading the model and converting a test signal"
  & $py -m mimicry selftest
  if ($LASTEXITCODE -ne 0) { Write-Warning "Neural self-test failed (see above). The app still works in pitch-only mode. Send me this output / logs\install.log." }
}

Say "Environment check"
& $py -m mimicry doctor

Write-Host "`nDONE.  Next:" -ForegroundColor Green
Write-Host "  1. Install the virtual microphone driver VB-CABLE (https://vb-audio.com/Cable/) and reboot - if doctor says it's missing."
Write-Host "  2. Double-click start.bat"
Stop-Transcript | Out-Null
