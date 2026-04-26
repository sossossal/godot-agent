param(
    [switch]$IncludeLive
)

$ErrorActionPreference = "Stop"

Write-Host "P3 governance targeted non-live checks"
python -m pytest `
    tests/test_governance.py `
    tests/test_api.py `
    tests/test_quality_dashboard.py `
    tests/test_migrations.py `
    -q

Write-Host "Full non-live suite"
python -m pytest -m "not live" -q

if ($IncludeLive) {
    Write-Host "Live sandbox checks"
    .\tools\run_live_sandbox_tests.ps1
} else {
    Write-Host "SKIP live sandbox checks. Re-run with -IncludeLive when Godot editor automation is available."
}
