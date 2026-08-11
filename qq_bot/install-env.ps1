$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $PSCommandPath
$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")
$requirements = Join-Path $ProjectRoot "requirements-local.txt"
if (-not (Test-Path -LiteralPath $requirements)) {
    $RepoRoot = Resolve-Path -LiteralPath (Join-Path $ProjectRoot "..")
    $requirements = Join-Path $RepoRoot "requirements-local.txt"
}

function Find-Python {
    if ($env:PYTHON_EXE -and (Test-Path -LiteralPath $env:PYTHON_EXE)) {
        return $env:PYTHON_EXE
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return $py.Source
    }
    throw "Python was not found. Install Python or set PYTHON_EXE."
}

$python = Find-Python
Write-Host "Project root: $ProjectRoot"
Write-Host "Requirements: $requirements"
Write-Host "Python: $python"

if (-not (Test-Path -LiteralPath $requirements)) {
    throw "Missing requirements file: $requirements"
}

if ((Split-Path -Leaf $python).ToLowerInvariant() -eq "py.exe") {
    & $python -3 -m pip install --upgrade pip
    & $python -3 -m pip install -r $requirements
} else {
    & $python -m pip install --upgrade pip
    & $python -m pip install -r $requirements
}

Write-Host ""
Write-Host "Python dependencies are ready."
Write-Host "External apps still need manual setup if not installed:"
Write-Host "- NapCat: log in with a QQ bot account."
Write-Host "- AstrBot: install or start it, then copy the plugin folder from qq_bot."
