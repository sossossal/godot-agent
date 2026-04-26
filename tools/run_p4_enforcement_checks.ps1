param(
    [switch]$IncludeLive
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

Write-Host "P4 governance enforcement targeted non-live checks"
python -m pytest `
    tests/test_governance.py `
    tests/test_cli.py `
    tests/test_api.py `
    -q

Write-Host "P4 advisory enforcement smoke"
.\tools\enforce_governance.ps1 `
    -ChangeType mcp_bridge `
    -Evidence tool_schema,security_notes,tests,docs `
    -ChangedPath bridge/remote_mcp_server.py,tests/test_remote_mcp_bridge.py,README.md `
    -Mode advisory `
    -Json

Write-Host "Full non-live suite"
python -m pytest -m "not live" -q

if ($IncludeLive) {
    Write-Host "Live sandbox checks"
    .\tools\run_live_sandbox_tests.ps1
} else {
    Write-Host "SKIP live sandbox checks. Re-run with -IncludeLive when Godot editor automation is available."
}
