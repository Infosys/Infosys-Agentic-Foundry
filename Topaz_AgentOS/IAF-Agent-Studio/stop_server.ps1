# ============================================================================
#  Stop the AgentOS server (local dev).
#
#  The detached server runs under pythonw (no console), so Ctrl+C can't reach
#  it. This stops ONLY the process running server.py (matched by command line),
#  so it won't touch other python/pythonw apps you may have running.
#
#  Usage:
#    powershell -ExecutionPolicy Bypass -File .\stop_server.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

$procs = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*server.py*" }

if (-not $procs) {
    Write-Host "No AgentOS server process found (already stopped)."
    exit 0
}

foreach ($p in $procs) {
    Write-Host ("Stopping AgentOS server (PID " + $p.ProcessId + ") ...")
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 1
Write-Host "Stopped."
