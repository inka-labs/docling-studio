# Removes Docling Studio for this Windows user (Settings > Apps > Docling Studio > Uninstall).
# Your data (%USERPROFILE%\.docling-studio) is kept unless you say otherwise. ASCII only (see install.ps1).

$ErrorActionPreference = 'Continue'
$Root = Join-Path $env:LOCALAPPDATA 'Docling Studio'
$App = Join-Path $Root 'app'
$Py = Join-Path $App '.pixi\envs\default\python.exe'
$Data = Join-Path $env:USERPROFILE '.docling-studio'

Write-Host 'Uninstall Docling Studio'
Write-Host '-------------------------'
$yes = Read-Host 'Remove Docling Studio from this computer? [y/N]'
if ($yes -notmatch '^[Yy]') { Write-Host 'Nothing was changed.'; Start-Sleep 2; exit 0 }

if (Test-Path $Py) {
    & $Py -X utf8 -m docling_studio.launch --stop --force *> $null   # stops running conversions too
    Push-Location $App; & $Py -X utf8 -m docling_studio.autostart uninstall *> $null; Pop-Location
}
# Anything of this installation's still running (a Studio that didn't answer), so its files can be deleted.
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($App, [StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

foreach ($dir in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $dir 'Docling Studio.lnk')
}
Remove-Item -Recurse -Force -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DoclingStudio' -ErrorAction SilentlyContinue
Set-Location $env:USERPROFILE
Remove-Item -Recurse -Force -Path $Root -ErrorAction SilentlyContinue
if (Test-Path $Root) {
    Write-Host "Some of Studio's files are in use; delete $Root after restarting." -ForegroundColor Yellow
} else {
    Write-Host "Removed Docling Studio's files and shortcuts." -ForegroundColor Green
}

if (Test-Path $Data) {
    Write-Host ''
    Write-Host "Your Studio data is in $Data (past runs and their outputs, presets, settings)."
    $wipe = Read-Host 'Delete it too? [y/N]'
    if ($wipe -match '^[Yy]') { Remove-Item -Recurse -Force $Data; Write-Host 'Deleted.' }
    else { Write-Host 'Kept. Installing Studio again picks it up.' }
}
Write-Host ''
Write-Host 'Saved API keys are in Credential Manager > Windows Credentials, under docling-studio.'
Write-Host "Your documents and Docling's downloaded models (%USERPROFILE%\.cache) weren't touched."
Read-Host 'Press Enter to close this window' | Out-Null
