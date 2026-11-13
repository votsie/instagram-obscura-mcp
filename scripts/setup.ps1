param(
    [switch]$SkipObscura,
    [switch]$SkipModel
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' }
if ((-not $SkipObscura -or -not $SkipModel) -and -not (Get-Command aria2c -ErrorAction SilentlyContinue)) { throw 'Install aria2c for segmented, verified downloads.' }
Push-Location $repo
try {
    uv sync --extra analysis
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    $options = @()
    if (-not $SkipObscura) { $options += '--obscura' }
    if (-not $SkipModel) { $options += '--model' }
    if ($options.Count -gt 0) {
        uv run instagram-mcp-setup @options
        if ($LASTEXITCODE -ne 0) { throw 'Runtime setup failed.' }
    }
    Write-Host 'Setup complete. Run: uv run instagram-mcp-doctor'
} finally { Pop-Location }
