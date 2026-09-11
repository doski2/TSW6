# Abre cmd.exe maximizado en monitor secundario (o primario si solo hay uno).
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Script,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CmdArgs
)

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Tsw6NativeWin {
    [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    public const int SW_MAXIMIZE = 3;
}
"@

$screen = [System.Windows.Forms.Screen]::AllScreens |
    Where-Object { -not $_.Primary } |
    Select-Object -First 1
if ($null -eq $screen) {
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen
}
$wa = $screen.WorkingArea

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path -LiteralPath $Script)) {
    Write-Error "No existe el script: $Script"
    exit 1
}

$quotedArgs = @()
foreach ($a in $CmdArgs) {
    if ($null -eq $a -or $a -eq '') { continue }
    $quotedArgs += ('"' + ($a -replace '"', '""') + '"')
}
$argLine = ($quotedArgs -join ' ')

# Solo consola P1; la GUI usa gui.py (_secondary_monitor_workarea), no estas vars.
$inner = "set TSW6_SECONDARY_LAUNCH=1"
$inner += " & cd /d `"$repo`""
$inner += " & call `"$Script`" $argLine"

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'cmd.exe'
$psi.Arguments = "/k $inner"
$psi.WorkingDirectory = $repo
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $false
$p = [Diagnostics.Process]::Start($psi)

if ($null -eq $p) {
    Write-Error 'No se pudo iniciar cmd.exe'
    exit 1
}

$deadline = (Get-Date).AddSeconds(8)
while ($p.MainWindowHandle -eq [IntPtr]::Zero -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 50
    try { $p.Refresh() } catch { break }
}

if ($p.MainWindowHandle -ne [IntPtr]::Zero) {
    [Tsw6NativeWin]::MoveWindow(
        $p.MainWindowHandle, $wa.X, $wa.Y, $wa.Width, $wa.Height, $true) | Out-Null
    [Tsw6NativeWin]::ShowWindow($p.MainWindowHandle, [Tsw6NativeWin]::SW_MAXIMIZE) | Out-Null
}

exit 0
