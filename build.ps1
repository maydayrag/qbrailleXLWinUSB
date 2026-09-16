$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $projectDir "manifest.ini"
$versionLine = Select-String -LiteralPath $manifestPath -Pattern '^version\s*=\s*"([^"]+)"$'
if (-not $versionLine) {
	throw "Could not read the add-on version from manifest.ini"
}
$version = $versionLine.Matches[0].Groups[1].Value
$distDir = Join-Path $projectDir "dist"
$outputPath = Join-Path $distDir "qbrailleXLWinUSB-$version.nvda-addon"
$stagingDir = Join-Path ([System.IO.Path]::GetTempPath()) ("qbrailleXLWinUSB-" + [guid]::NewGuid())

try {
	New-Item -ItemType Directory -Path $distDir -Force | Out-Null
	New-Item -ItemType Directory -Path $stagingDir | Out-Null
	Copy-Item -LiteralPath $manifestPath -Destination $stagingDir
	Copy-Item -LiteralPath (Join-Path $projectDir "doc") -Destination $stagingDir -Recurse
	Copy-Item -LiteralPath (Join-Path $projectDir "locale") -Destination $stagingDir -Recurse
	Copy-Item -LiteralPath (Join-Path $projectDir "addon\brailleDisplayDrivers") -Destination $stagingDir -Recurse
	Get-ChildItem -LiteralPath $stagingDir -Directory -Filter "__pycache__" -Recurse |
		Remove-Item -Recurse -Force

	$zipPath = [System.IO.Path]::ChangeExtension($outputPath, ".zip")
	if (Test-Path -LiteralPath $zipPath) {
		Remove-Item -LiteralPath $zipPath
	}
	Compress-Archive -Path (Join-Path $stagingDir "*") -DestinationPath $zipPath -CompressionLevel Optimal
	Move-Item -LiteralPath $zipPath -Destination $outputPath -Force
	Write-Output $outputPath
}
finally {
	if (Test-Path -LiteralPath $stagingDir) {
		Remove-Item -LiteralPath $stagingDir -Recurse -Force
	}
}
