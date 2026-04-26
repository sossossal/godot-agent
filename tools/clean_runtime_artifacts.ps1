[CmdletBinding()]
param(
    [string]$RepoRoot,
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$script:CleanupState = [ordered]@{
    Preview = New-Object System.Collections.Generic.List[string]
    Removed = New-Object System.Collections.Generic.List[string]
    Skipped = New-Object System.Collections.Generic.List[object]
    Created = New-Object System.Collections.Generic.List[string]
}

function Resolve-InsideRepo {
    param(
        [string]$Root,
        [string]$Candidate
    )

    $resolvedRoot = (Resolve-Path $Root).Path
    $resolvedCandidate = (Resolve-Path $Candidate).Path
    if (-not $resolvedCandidate.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside repo root: $resolvedCandidate"
    }
    return $resolvedCandidate
}

function Remove-ManagedPath {
    param(
        [string]$Root,
        [string]$Target,
        [switch]$PreviewOnly
    )

    if (-not (Test-Path $Target)) {
        return
    }

    $resolvedTarget = Resolve-InsideRepo -Root $Root -Candidate $Target
    if ($PreviewOnly) {
        $script:CleanupState.Preview.Add($resolvedTarget) | Out-Null
        Write-Output "PREVIEW $resolvedTarget"
        return
    }

    try {
        Remove-Item -LiteralPath $resolvedTarget -Recurse -Force -ErrorAction Stop
        $script:CleanupState.Removed.Add($resolvedTarget) | Out-Null
        Write-Output "REMOVED $resolvedTarget"
    } catch {
        $script:CleanupState.Skipped.Add([pscustomobject]@{
            Path = $resolvedTarget
            Message = $_.Exception.Message
        }) | Out-Null
        Write-Output "SKIPPED $resolvedTarget :: $($_.Exception.Message)"
    }
}

function Clear-ManagedDirectory {
    param(
        [string]$Root,
        [string]$Target,
        [switch]$PreviewOnly,
        [string[]]$ExcludeNames = @()
    )

    if (-not (Test-Path $Target)) {
        return
    }

    $resolvedTarget = Resolve-InsideRepo -Root $Root -Candidate $Target
    Get-ChildItem -LiteralPath $resolvedTarget -Force -ErrorAction SilentlyContinue | ForEach-Object {
        if ($ExcludeNames -contains $_.Name) {
            return
        }
        if (-not $PreviewOnly -and $_.PSIsContainer) {
            Clear-ManagedDirectory -Root $Root -Target $_.FullName -ExcludeNames @()
        }
        Remove-ManagedPath -Root $Root -Target $_.FullName -PreviewOnly:$PreviewOnly
    }
}

function Ensure-ManagedFile {
    param(
        [string]$Path,
        [string]$Content = ""
    )

    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        $script:CleanupState.Created.Add($parent) | Out-Null
        Write-Output "CREATED $parent"
    }

    if (-not (Test-Path $Path)) {
        Set-Content -LiteralPath $Path -Value $Content -NoNewline -Encoding UTF8
        $script:CleanupState.Created.Add($Path) | Out-Null
        Write-Output "CREATED $Path"
    }
}

function Write-CleanupSummary {
    param([switch]$PreviewOnly)

    Write-Output ("SUMMARY preview={0} removed={1} skipped={2} created={3}" -f `
        $script:CleanupState.Preview.Count, `
        $script:CleanupState.Removed.Count, `
        $script:CleanupState.Skipped.Count, `
        $script:CleanupState.Created.Count)

    if ($script:CleanupState.Skipped.Count -eq 0 -or $PreviewOnly) {
        return
    }

    Write-Output "ATTENTION Some runtime artifacts could not be removed."
    foreach ($entry in $script:CleanupState.Skipped) {
        Write-Output "ATTENTION $($entry.Path) :: $($entry.Message)"
    }

    $aclDenied = @(
        $script:CleanupState.Skipped |
            Where-Object { $_.Message -match "denied" }
    )
    if ($aclDenied.Count -eq 0) {
        return
    }

    Write-Output "ACL_REPAIR Run .\tools\fix_acl_artifacts.ps1 in an elevated PowerShell window to reclaim and delete the blocked paths."
    Write-Output "ACL_REPAIR Preview with .\tools\fix_acl_artifacts.ps1 -Preview before applying the deletion."
    Write-Output "ACL_REPAIR Blocked paths detected in this run:"
    foreach ($entry in $aclDenied) {
        Write-Output ("ACL_REPAIR   {0}" -f $entry.Path)
    }
}

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

$contentDirectories = @(
    (Join-Path $RepoRoot ".godot"),
    (Join-Path $RepoRoot "logs"),
    (Join-Path $RepoRoot "api_server\static\dist")
)

$paths = @(
    (Join-Path $RepoRoot "tests\test_report.json")
)

$globs = @(
    (Join-Path $RepoRoot "tests\.tmp*"),
    (Join-Path $RepoRoot "pytest-cache-files-*")
)

foreach ($directory in $contentDirectories) {
    $excludeNames = @()
    if ($directory -like "*api_server\static\dist") {
        $excludeNames = @(".gitkeep")
    }
    Clear-ManagedDirectory -Root $RepoRoot -Target $directory -PreviewOnly:$Preview -ExcludeNames $excludeNames
}

foreach ($path in $paths) {
    Remove-ManagedPath -Root $RepoRoot -Target $path -PreviewOnly:$Preview
}

foreach ($pattern in $globs) {
    Get-ChildItem -Path $pattern -Force -ErrorAction SilentlyContinue |
        ForEach-Object {
            Remove-ManagedPath -Root $RepoRoot -Target $_.FullName -PreviewOnly:$Preview
        }
}

if (-not $Preview) {
    foreach ($dir in @(
        (Join-Path $RepoRoot "logs"),
        (Join-Path $RepoRoot "logs\backups"),
        (Join-Path $RepoRoot "logs\reports"),
        (Join-Path $RepoRoot "logs\test_artifacts"),
        (Join-Path $RepoRoot "api_server\static\dist")
    )) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            $script:CleanupState.Created.Add($dir) | Out-Null
            Write-Output "CREATED $dir"
        }
    }

    Ensure-ManagedFile -Path (Join-Path $RepoRoot "api_server\static\dist\.gitkeep")
}

Write-CleanupSummary -PreviewOnly:$Preview
