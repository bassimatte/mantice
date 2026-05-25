# sync_docs.ps1 — copy engine/static/index.html → docs/index.html
# and inject the production API base URL for GitHub Pages.
#
# Usage: .\sync_docs.ps1
# Run from repo root before committing a docs update.

$src = "engine\static\index.html"
$dst = "docs\index.html"

$LOCAL  = "const MANTICE_API_BASE = window.MANTICE_API_BASE || '';"
$REMOTE = "const MANTICE_API_BASE = 'https://mantice.onrender.com';"

Copy-Item $src $dst -Force

$content = Get-Content $dst -Raw
if ($content -notmatch [regex]::Escape($LOCAL)) {
    Write-Error "ERROR: Could not find MANTICE_API_BASE placeholder in $dst — sync aborted."
    exit 1
}

$content = $content.Replace($LOCAL, $REMOTE)
Set-Content $dst $content -NoNewline

# Confirm
$check = Select-String -Path $dst -Pattern "mantice\.onrender\.com" -Quiet
if (-not $check) {
    Write-Error "ERROR: API base injection failed — docs/index.html still points to empty string."
    exit 1
}

Write-Host "OK  docs/index.html synced with MANTICE_API_BASE = 'https://mantice.onrender.com'"
