$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
$resultFolder = Join-Path $PSScriptRoot ('results-local/' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
python -m gwix all --config configs/synthetic.json --out $resultFolder
if ($LASTEXITCODE -ne 0) { throw 'Run failed' }
Write-Host "Synthetic results saved to $resultFolder"
