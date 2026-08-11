param(
    [switch]$SkipClean
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()
try {
    [Console]::OutputEncoding = $OutputEncoding
} catch {
    # Some hosts do not allow changing console encoding; build output remains valid.
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SpecPath = Join-Path $RepoRoot "NavisWorks_Line_flow_Tools.spec"
$IconPngPath = Join-Path $RepoRoot "assets\branding\ie_mark_v2.png"
$IconIcoPath = Join-Path $RepoRoot "assets\branding\pipeline_ops_v2.ico"
$SplashPngPath = Join-Path $RepoRoot "assets\branding\startup_splash_v2.png"
$VersionInfoPath = Join-Path $RepoRoot "assets\branding\windows_version_info_v4.txt"
$AppVersion = ""
$VenvDir = Join-Path $RepoRoot ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$ExeName = "NavisWorks_Line_flow_Tools.exe"
$ManifestName = "NavisWorks_Line_flow_Tools.manifest.json"
$DistDir = Join-Path $RepoRoot "dist"
$BuildDir = Join-Path $RepoRoot "build"
$ExePath = Join-Path $DistDir $ExeName
$ManifestPath = Join-Path $DistDir $ManifestName

function Fail([string]$Message) {
    Write-Host "[build_exe] ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Assert-RepoChild([string]$Path) {
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Fail "Refusing to touch path outside repo: $fullPath"
    }
    return $fullPath
}

function Run-Checked([string]$Label, [scriptblock]$Command) {
    Write-Host "[build_exe] $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        Fail "$Label failed with exit code $LASTEXITCODE"
    }
}

function Read-GitValue([string[]]$ArgsList) {
    $value = & git @ArgsList 2>$null
    if ($LASTEXITCODE -ne 0 -or $null -eq $value) {
        return ""
    }
    return (($value | Select-Object -First 1).ToString()).Trim()
}

Write-Host "[build_exe] RepoRoot = $RepoRoot"

if (-not (Test-Path -LiteralPath $VenvDir -PathType Container)) {
    Fail "Missing .venv. Create and prepare the project virtualenv first; this build script will not install it silently."
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    Fail "Missing .venv Python: $PythonExe"
}
if (-not (Test-Path -LiteralPath $SpecPath -PathType Leaf)) {
    Fail "Missing PyInstaller spec: $SpecPath"
}
if (-not (Test-Path -LiteralPath $IconPngPath -PathType Leaf)) {
    Fail "Missing application icon PNG: $IconPngPath"
}
if (-not (Test-Path -LiteralPath $IconIcoPath -PathType Leaf)) {
    Fail "Missing application icon ICO: $IconIcoPath"
}
if (-not (Test-Path -LiteralPath $SplashPngPath -PathType Leaf)) {
    Fail "Missing startup splash PNG: $SplashPngPath"
}
if (-not (Test-Path -LiteralPath $VersionInfoPath -PathType Leaf)) {
    Fail "Missing Windows version resource: $VersionInfoPath"
}

$pythonVersion = ""
try {
    $pythonVersion = (& $PythonExe -c "import sys; print(sys.version.split()[0])" 2>&1)
    if ($LASTEXITCODE -ne 0) {
        Fail ".venv Python exists but cannot run. Output: $pythonVersion"
    }
} catch {
    Fail ".venv Python exists but cannot run. $($_.Exception.Message)"
}

try {
    $versionOutput = $null
    $versionExitCode = 1
    Push-Location $RepoRoot
    try {
        $versionOutput = & $PythonExe -c "from core.release_update import CURRENT_VERSION; print(CURRENT_VERSION)" 2>&1
        $versionExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $AppVersion = ([string]($versionOutput | Select-Object -First 1)).Trim()
    if ($versionExitCode -ne 0 -or $AppVersion -notmatch '^\d+\.\d+\.\d+$') {
        Fail "Invalid application version from core.release_update: $AppVersion"
    }
} catch {
    Fail "Could not read application version. $($_.Exception.Message)"
}

$versionParts = $AppVersion.Split('.')
$versionTuple = "($($versionParts[0]), $($versionParts[1]), $($versionParts[2]), 0)"
$versionInfoText = Get-Content -LiteralPath $VersionInfoPath -Raw
foreach ($expected in @(
    "filevers=$versionTuple",
    "prodvers=$versionTuple",
    "StringStruct('FileVersion', '$AppVersion')",
    "StringStruct('ProductVersion', '$AppVersion')"
)) {
    if (-not $versionInfoText.Contains($expected)) {
        Fail "Windows version resource is out of sync with app version $AppVersion"
    }
}

$pyinstallerVersion = ""
try {
    $pyinstallerVersion = (& $PythonExe -c "import PyInstaller; print(PyInstaller.__version__)" 2>&1)
    if ($LASTEXITCODE -ne 0) {
        Fail "PyInstaller is not importable from .venv. Install it in .venv first. Output: $pyinstallerVersion"
    }
} catch {
    Fail "PyInstaller is not importable from .venv. Install it in .venv first. $($_.Exception.Message)"
}

if (-not $SkipClean) {
    foreach ($path in @($BuildDir, $DistDir)) {
        if (Test-Path -LiteralPath $path) {
            $safePath = Assert-RepoChild $path
            Write-Host "[build_exe] Removing $safePath"
            Remove-Item -LiteralPath $safePath -Recurse -Force
        }
    }
}

Push-Location $RepoRoot
try {
    Run-Checked "PyInstaller $pyinstallerVersion onefile build" {
        & $PythonExe -m PyInstaller --clean --noconfirm $SpecPath
    }
} finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    Fail "Build finished but EXE was not found: $ExePath"
}

# Windows GUI executables return control immediately when invoked with `&`.
# Start-Process + WaitForExit performs a real packaged lifecycle check.
$previousQpaPlatform = $env:QT_QPA_PLATFORM
$previousSuppressSplash = $env:PYINSTALLER_SUPPRESS_SPLASH_SCREEN
$smokeWatch = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $env:QT_QPA_PLATFORM = "offscreen"
    # The smoke test must stay invisible on the operator's desktop.  The
    # bootloader splash has its own Tk window and is independent of Qt.
    $env:PYINSTALLER_SUPPRESS_SPLASH_SCREEN = "1"
    $smokeProcess = Start-Process `
        -FilePath $ExePath `
        -ArgumentList @("--smoke-test") `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -PassThru
    if (-not $smokeProcess.WaitForExit(45000)) {
        try { $smokeProcess.Kill($true) } catch {}
        Fail "Packaged smoke test timed out after 45 seconds"
    }
    $smokeProcess.WaitForExit()
    if ($smokeProcess.ExitCode -ne 0) {
        Fail "Packaged smoke test failed with exit code $($smokeProcess.ExitCode)"
    }
} finally {
    $smokeWatch.Stop()
    if ($null -eq $previousQpaPlatform) {
        Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    } else {
        $env:QT_QPA_PLATFORM = $previousQpaPlatform
    }
    if ($null -eq $previousSuppressSplash) {
        Remove-Item Env:PYINSTALLER_SUPPRESS_SPLASH_SCREEN -ErrorAction SilentlyContinue
    } else {
        $env:PYINSTALLER_SUPPRESS_SPLASH_SCREEN = $previousSuppressSplash
    }
}
Write-Host (
    "[build_exe] Packaged smoke OK ({0:N2}s)" -f $smokeWatch.Elapsed.TotalSeconds
)

$exeItem = Get-Item -LiteralPath $ExePath
$hash = (Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()

$gitCommit = ""
$gitBranch = ""
$gitDirty = $true
$sourceRepo = $RepoRoot
try {
    Push-Location $RepoRoot
    $gitCommit = Read-GitValue @("rev-parse", "HEAD")
    $gitBranch = Read-GitValue @("rev-parse", "--abbrev-ref", "HEAD")
    $remote = Read-GitValue @("config", "--get", "remote.origin.url")
    if ($remote) {
        $sourceRepo = $remote
    }
    $status = & git status --porcelain 2>$null
    $gitDirty = $LASTEXITCODE -eq 0 -and [bool](($status -join "`n").Trim())
} catch {
    Write-Warning "[build_exe] Could not read git metadata: $($_.Exception.Message)"
} finally {
    Pop-Location
}

$manifest = [ordered]@{
    appVersion = $AppVersion
    exeName = $ExeName
    exePath = $ExeName
    builtAt = (Get-Date).ToUniversalTime().ToString("o")
    sourceRepo = $sourceRepo
    gitCommit = $gitCommit
    gitBranch = $gitBranch
    gitDirty = $gitDirty
    fileSize = $exeItem.Length
    sha256 = $hash
    pythonVersion = [string]$pythonVersion
    pyinstallerVersion = [string]$pyinstallerVersion
}

if (-not (Test-Path -LiteralPath $DistDir -PathType Container)) {
    New-Item -ItemType Directory -Path $DistDir | Out-Null
}
$manifestJson = $manifest | ConvertTo-Json -Depth 4
# Windows PowerShell 5.1 writes a BOM for ``-Encoding UTF8``.  Use the .NET
# encoder explicitly so Release manifests are identical across PowerShell
# editions and remain readable by strict JSON clients.
[System.IO.File]::WriteAllText(
    $ManifestPath,
    $manifestJson,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "[build_exe] OK"
Write-Host "[build_exe] EXE      = $($exeItem.FullName)"
Write-Host "[build_exe] Size     = $($exeItem.Length) bytes"
Write-Host "[build_exe] Modified = $($exeItem.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"
Write-Host "[build_exe] SHA256   = $hash"
Write-Host "[build_exe] Manifest = $ManifestPath"
