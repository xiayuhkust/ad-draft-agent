# Deploy AD assets to Tencent CloudBase static hosting under /ad
# (gunfight-vfx-lab owns the site root; do NOT deploy to /)
#
#   /ad/       practice web page (index.html + data + icons), no password
#   /ad/dist/  hot-update source for updater (manifest.json + files/)
#   /ad/dl/    installer exe (referenced by manifest installerUrl)
#
# Usage: powershell -File scripts\deploy_cloudbase.ps1 [-SkipInstaller]
# Run AFTER scripts\publish_update.py (dist must be fresh).
# NOTE: keep this file ASCII-only -- PS 5.1 reads BOM-less files as ANSI.
param([switch]$SkipInstaller)

$ENVID = "xiayuyosemi-d2goomeghaee6ee5b"
$URL = "https://xiayuyosemi-d2goomeghaee6ee5b-1450725484.tcloudbaseapp.com"
$root = Split-Path $PSScriptRoot -Parent
$ver = (Get-Content "$root\VERSION" -Raw).Trim()

# --- web page: stage without overlay.html (useless outside the box host),
# stamp bundle.js query so CDN long-cache never serves stale data
$staging = Join-Path $env:TEMP "ad-web-deploy"
Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $staging | Out-Null
Copy-Item "$root\web\index.html" $staging
Copy-Item -Recurse "$root\web\data", "$root\web\img" $staging
$stamp = Get-Date -Format "yyyyMMddHHmmss"
$idx = Join-Path $staging "index.html"
$html = [System.IO.File]::ReadAllText($idx)
$html = $html -replace 'data/bundle\.js"', "data/bundle.js?v=$stamp`""
[System.IO.File]::WriteAllText($idx, $html, (New-Object System.Text.UTF8Encoding($false)))

tcb hosting deploy $staging ad -e $ENVID
if ($LASTEXITCODE -ne 0) { Write-Output "web deploy FAILED"; exit 1 }

# --- update source (updater cache-busts via query params by itself)
tcb hosting deploy "$root\dist" ad/dist -e $ENVID
if ($LASTEXITCODE -ne 0) { Write-Output "dist deploy FAILED"; exit 1 }

# --- installer
if (-not $SkipInstaller) {
  $setup = "$root\build\installer\ADBox-Setup-$ver.exe"
  if (Test-Path $setup) {
    tcb hosting deploy $setup "ad/dl/ADBox-Setup-$ver.exe" -e $ENVID
    if ($LASTEXITCODE -ne 0) { Write-Output "installer deploy FAILED"; exit 1 }
  } else {
    Write-Output "installer not found, skipped: $setup"
  }
}

Write-Output ""
Write-Output "Web page : $URL/ad/"
Write-Output "UpdateSrc: $URL/ad/dist"
Write-Output "Installer: $URL/ad/dl/ADBox-Setup-$ver.exe"
Write-Output "(CDN cache: html ~2 min; verify in incognito)"
