# Set up and start one unattended Windows GUI run of MarkdownGlance.
#
#   powershell -ep bypass -f d:\w.ps1                  # the export suite
#   powershell -ep bypass -f d:\w.ps1 -Suite images    # step 6
#   powershell -ep bypass -f d:\w.ps1 -Suite outline   # steps 9 and 10
#
# Assumes Sublime Text 4200 is already installed (p.ps1 did that once, and the
# `virtio-qxl` snapshot carries it). This refreshes the package from the CD,
# lays the fixtures out, installs the WinProbe driver and starts the editor.
# Everything after that is the probe talking to the host collector on
# 10.0.2.2:8099 (and, for the images suite, the image server on :8100).

param([ValidateSet('export', 'images', 'outline', 'widths')][string]$Suite = 'export')

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Start-Transcript -Path "$env:USERPROFILE\Desktop\winprobe.log" -Force
"suite: $Suite"

$exe = 'C:\Program Files\Sublime Text\sublime_text.exe'
if (-not (Test-Path $exe)) { throw "Sublime Text is not installed at $exe" }
'build ' + (Get-Item $exe).VersionInfo.FileVersion

'== a run starts from a closed editor and a closed browser =='
# Re-running has to reload the probe, and Start-Process on a running editor
# only focuses it.
# Measured: Stop-Process left the editor running once, and the run then went
# on inside the previous session -- its tabs, its groups and its old probe
# still ticking. taskkill plus a wait for the process to actually go is the
# version that holds, and a run that cannot get a closed editor is worthless.
foreach ($image in 'sublime_text.exe', 'msedge.exe') {
    Start-Process taskkill -ArgumentList '/IM', $image, '/F' -Wait -NoNewWindow
}
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Process -Name 'sublime_text' -ErrorAction SilentlyContinue) -and
       (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
}
if (Get-Process -Name 'sublime_text' -ErrorAction SilentlyContinue) {
    throw 'Sublime Text is still running; a run must start from a closed editor'
}
'editor closed'
Start-Sleep -Seconds 2

$packages = Join-Path $env:APPDATA 'Sublime Text\Packages'
New-Item -ItemType Directory -Force -Path $packages | Out-Null

function Copy-Tree($name) {
    $dest = Join-Path $packages $name
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Copy-Item -Recurse (Join-Path $PSScriptRoot $name) $dest
    # Everything off a CD arrives read-only, which stops Sublime writing caches.
    Get-ChildItem -Recurse -File $dest | ForEach-Object { $_.IsReadOnly = $false }
    '{0} files in {1}' -f (Get-ChildItem -Recurse -File $dest).Count, $dest
}

function Copy-Fixtures($from, $to) {
    New-Item -ItemType Directory -Force -Path $to | Out-Null
    Copy-Item -Force (Join-Path $PSScriptRoot "fixtures\$from\*") $to
    Get-ChildItem -File $to | ForEach-Object { $_.IsReadOnly = $false }
    '{0} files in {1}' -f (Get-ChildItem -File $to).Count, $to
}

'== package and probe =='
Copy-Tree 'MarkdownGlance'
Copy-Tree 'WinProbe'

'== libraries =='
# 0.4.x needs the ecosystem Markdown and pymdown-extensions. Package Control
# installs them with the package; this guest carries a manual install, so the
# same two library trees come off the CD into the 3.8 library directory.
$lib = Join-Path $env:APPDATA 'Sublime Text\Lib\python38'
New-Item -ItemType Directory -Force -Path $lib | Out-Null
Copy-Item -Recurse -Force (Join-Path $PSScriptRoot 'libs\*') $lib
Get-ChildItem -Recurse -File $lib | ForEach-Object { $_.IsReadOnly = $false }
Get-ChildItem $lib | Select-Object -ExpandProperty Name

# Without this the probe loads into the 3.3 plugin host, and nothing it reads
# out of MarkdownGlance's own session is reachable from there -- measured:
# `sys.version` came back 3.3.7 and the container import failed.
'3.8' | Set-Content -Encoding ASCII (Join-Path $packages 'WinProbe\.python-version')
$Suite | Set-Content -Encoding ASCII (Join-Path $packages 'WinProbe\suite.txt')

'== settings =='
$user = Join-Path $packages 'User'
New-Item -ItemType Directory -Force -Path $user | Out-Null
# One settings file per suite: only what that suite's step actually needs.
$settings = switch ($Suite) {
    'images'  { '{ "allow_insecure_remote_images": true, "remote_timeout_seconds": 3.0 }' }
    { $_ -in 'outline', 'widths' } { '{ "auto_width": true, "enable_toc": true }' }
    default   { '{ "enable_math": true, "enable_mermaid": true }' }
}
$settings | Set-Content -Encoding UTF8 (Join-Path $user 'MarkdownGlance.sublime-settings')
$settings
# A run must not inherit the last one's open files.
'{ "hot_exit": false, "remember_open_files": false, "hardware_acceleration": "none" }' |
    Set-Content -Encoding UTF8 (Join-Path $user 'Preferences.sublime-settings')

'== fixtures =='
# The directory name carries a space and a hash on purpose: the exported page
# has to encode both in the URL it gives the relative image.
Copy-Fixtures 'export' (Join-Path "$env:USERPROFILE\Desktop" 'fixture space #hash')
Copy-Fixtures 'images' "$env:USERPROFILE\Desktop\images"
Copy-Fixtures 'outline' "$env:USERPROFILE\Desktop\outline"
$math = "$env:USERPROFILE\Desktop\math.md"
Copy-Item (Join-Path $PSScriptRoot 'fixtures\math.md') $math -Force
(Get-Item $math).IsReadOnly = $false
$math

if ($Suite -eq 'export') {
    '== edge past its first run =='
    # Otherwise the first `webbrowser.open` lands behind a welcome wizard and
    # the screenshots show that instead of the exported page. The policy key
    # under HKCU\Software\Policies is denied to a non-elevated user -- measured,
    # the whole script died there -- so start the browser once with the flags
    # instead and leave it running; later file:// URLs open as tabs in it.
    try {
        Start-Process 'msedge' -ArgumentList '--no-first-run',
            '--no-default-browser-check', 'about:blank'
        Start-Sleep -Seconds 8
    } catch {
        'could not pre-start Edge: ' + $_.Exception.Message
    }
}

'== host collector reachable? =='
foreach ($url in 'http://10.0.2.2:8099/', 'http://10.0.2.2:8100/ping') {
    try {
        '{0} -> {1}' -f $url, (Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 10).Content.Trim()
    } catch {
        '{0} -> NOT reachable: {1}' -f $url, $_.Exception.Message
    }
}

'== starting Sublime Text; the probe drives from here =='
Stop-Transcript
Start-Process $exe
