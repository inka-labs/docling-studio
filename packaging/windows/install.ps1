# Installs, or updates, Docling Studio for this Windows user. Run by "Install Docling Studio.cmd".
#
#   %LOCALAPPDATA%\Docling Studio\    app\ (Studio and its environment), bin\pixi.exe, uninstall.ps1
#   Start menu + Desktop shortcut      opens Studio (starts it if needed, signs you in)
#   %USERPROFILE%\.docling-studio\    your runs, presets, settings (kept on update)
#
# No administrator rights; listed under Settings > Apps for uninstalling. Built by packaging/build_release.py.
# ASCII only: Windows PowerShell 5.1 misreads UTF-8 scripts without a BOM.
#
# Studio's "Update now" runs it hidden with DOCLING_STUDIO_UNATTENDED=1: no prompts, and Studio is
# started again in the background (the browser tab that asked for the update reconnects).
param([Parameter(Mandatory = $true)][string]$Source)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest is very slow with its progress bar
$PixiVersion = '__PIXI_VERSION__'
$StudioVersion = '__STUDIO_VERSION__'
$Root = Join-Path $env:LOCALAPPDATA 'Docling Studio'
$App = Join-Path $Root 'app'
$Bin = Join-Path $Root 'bin'
$Pixi = Join-Path $Bin 'pixi.exe'
$EnvDir = Join-Path $App '.pixi\envs\default'
$Py = Join-Path $EnvDir 'python.exe'
$Pyw = Join-Path $EnvDir 'pythonw.exe'
$Unattended = [bool]$env:DOCLING_STUDIO_UNATTENDED

function Finish {
    if ($Unattended) { return }
    Write-Host ''; Read-Host 'Press Enter to close this window' | Out-Null
}
function Fail([string]$Message) {
    Write-Host ''
    Write-Host "X $Message" -ForegroundColor Red
    Write-Host '  Nothing you had in Studio (runs, presets, services) was changed.'
    if ($Unattended -and (Test-Path $Py)) {
        # back as it was, if it can be
        try { Start-Process -FilePath $Pyw -ArgumentList '-X', 'utf8', '-m', 'docling_studio.launch', '--no-browser' -WorkingDirectory $App -Wait } catch { }
    }
    Finish
    exit 1
}

try {
    if (-not $Unattended) { Clear-Host }
    Write-Host "Docling Studio $StudioVersion ($(Get-Date))"
    Write-Host '------------------------------'
    $Source = $Source.TrimEnd('\')
    if (-not (Test-Path (Join-Path $Source 'pixi.toml'))) { Fail 'Open this from the unzipped Docling Studio folder (its app folder is missing).' }
    New-Item -ItemType Directory -Force -Path $Bin | Out-Null

    # 1. pixi: installs Python and packages, for Studio and Docling.
    $have = ''
    if (Test-Path $Pixi) { $have = (& $Pixi --version) 2>$null }
    if ($have -ne "pixi $PixiVersion") {
        Write-Host "-> Downloading pixi $PixiVersion (installs Docling and the Python packages Studio uses)..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $zip = Join-Path $env:TEMP "pixi-$PixiVersion.zip"
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/prefix-dev/pixi/releases/download/v$PixiVersion/pixi-x86_64-pc-windows-msvc.zip" -OutFile $zip
        Expand-Archive -Force -Path $zip -DestinationPath $Bin
        Remove-Item $zip
    }

    # 2. An update: stop the Studio that's running (it refuses while a conversion runs).
    if (Test-Path $Py) {
        & $Py -X utf8 -m docling_studio.launch --stop
        if ($LASTEXITCODE -ne 0) { Fail 'Studio is busy (see above). Let it finish, or quit it in Studio > Settings > Quit Studio, then run this installer again.' }
    }

    # 3. Studio's files (its environment, .pixi, is kept so an update is quick).
    Write-Host '-> Copying Studio...'
    robocopy $Source $App /MIR /XD (Join-Path $App '.pixi') /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "Copying Studio's files failed (robocopy code $LASTEXITCODE)." }

    # 4. Studio's own Python and packages.
    Write-Host "-> Installing Studio's Python and packages (a few minutes the first time)..."
    & $Pixi install --manifest-path (Join-Path $App 'pixi.toml') --frozen
    if ($LASTEXITCODE -ne 0) { Fail 'Installing the packages failed (see above). Check your internet connection and try again.' }

    # 5. Shortcuts: Start menu and Desktop.
    Write-Host '-> Adding Docling Studio to the Start menu and Desktop...'
    $shell = New-Object -ComObject WScript.Shell
    foreach ($dir in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
        $link = $shell.CreateShortcut((Join-Path $dir 'Docling Studio.lnk'))
        $link.TargetPath = $Pyw
        $link.Arguments = '-X utf8 -m docling_studio.launch'
        $link.WorkingDirectory = $App
        $link.IconLocation = (Join-Path $App 'packaging\windows\icon.ico')
        $link.Description = 'Open Docling Studio'
        $link.Save()
    }

    # 6. Settings > Apps: an entry to uninstall it.
    Copy-Item -Force (Join-Path $App 'packaging\windows\uninstall.ps1') (Join-Path $Root 'uninstall.ps1')
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DoclingStudio'
    New-Item -Force -Path $key | Out-Null
    $uninstall = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Root 'uninstall.ps1') + '"'
    $values = @{
        DisplayName = 'Docling Studio'; DisplayVersion = $StudioVersion; InstallLocation = $Root
        DisplayIcon = (Join-Path $App 'packaging\windows\icon.ico'); UninstallString = $uninstall
    }
    foreach ($name in $values.Keys) { Set-ItemProperty -Path $key -Name $name -Value $values[$name] }
    Set-ItemProperty -Path $key -Name NoModify -Value 1 -Type DWord
    Set-ItemProperty -Path $key -Name NoRepair -Value 1 -Type DWord

    Write-Host ''
    if ($Unattended) {
        Write-Host "Docling Studio $StudioVersion is installed. Starting it again..."
        Start-Process -FilePath $Pyw -ArgumentList '-X', 'utf8', '-m', 'docling_studio.launch', '--no-browser' -WorkingDirectory $App -Wait
        exit 0
    }
    Write-Host "Docling Studio $StudioVersion is installed. Opening it in your browser..." -ForegroundColor Green
    Write-Host '  Next time, open Docling Studio from the Start menu or the Desktop.'
    Start-Process -FilePath $Pyw -ArgumentList '-X', 'utf8', '-m', 'docling_studio.launch' -WorkingDirectory $App
    Start-Sleep -Seconds 3
}
catch {
    Fail ("The installation stopped: " + $_.Exception.Message)
}
