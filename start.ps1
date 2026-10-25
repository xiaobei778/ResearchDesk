param([int]$Port = 18765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtime = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtime)) {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if (-not $command) { throw 'Install Python 3.10+ and run: python -m pip install -r requirements.txt' }
    $runtime = $command.Source
}
$appArgs = @('-X', 'utf8', 'app.py', '--port', "$Port")
if ($NoBrowser) { $appArgs += '--no-browser' }
& $runtime @appArgs
exit $LASTEXITCODE
