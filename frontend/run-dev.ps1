# Run the React chat UI using portable Node.js (no system install required).
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$nodeDir = Join-Path $projectRoot ".tools\node"
$nodeExe = Join-Path $nodeDir "node.exe"
$npmCmd = Join-Path $nodeDir "npm.cmd"

if (-not (Test-Path $nodeExe)) {
    Write-Host "Portable Node.js not found. Run from project root:" -ForegroundColor Yellow
    Write-Host "  .\.tools\install-node.ps1" -ForegroundColor Yellow
    exit 1
}

$env:PATH = "$nodeDir;$env:PATH"
Set-Location $PSScriptRoot

if (-not (Test-Path "node_modules")) {
    Write-Host "Installing dependencies..."
    & $npmCmd install --prefix "$PSScriptRoot"
}

Write-Host "Starting Vite dev server at http://localhost:5173"
Write-Host "Ensure the API is running: uvicorn app.main:app --reload"
& $nodeExe (Join-Path $PSScriptRoot "node_modules\vite\bin\vite.js") --config (Join-Path $PSScriptRoot "vite.config.ts")
