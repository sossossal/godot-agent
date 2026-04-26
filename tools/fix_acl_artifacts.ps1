[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string[]]$Targets,
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$script:RepairState = [ordered]@{
    Preview = New-Object System.Collections.Generic.List[string]
    Removed = New-Object System.Collections.Generic.List[string]
    Failed = New-Object System.Collections.Generic.List[object]
}

function Get-NormalizedPath {
    param([string]$Path)

    return [System.IO.Path]::GetFullPath($Path)
}

function Test-IsInsideRepo {
    param(
        [string]$Root,
        [string]$Candidate
    )

    $normalizedRoot = Get-NormalizedPath -Path $Root
    $normalizedCandidate = Get-NormalizedPath -Path $Candidate
    $rootPrefix = $normalizedRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    return (
        $normalizedCandidate.Equals($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $normalizedCandidate.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)
    )
}

function Test-IsManagedRuntimeArtifact {
    param(
        [string]$Root,
        [string]$Candidate
    )

    if (-not (Test-IsInsideRepo -Root $Root -Candidate $Candidate)) {
        return $false
    }

    $normalizedRoot = Get-NormalizedPath -Path $Root
    $normalizedCandidate = Get-NormalizedPath -Path $Candidate
    $rootPrefix = $normalizedRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    if ($normalizedCandidate.Equals($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        $relative = ''
    } elseif ($normalizedCandidate.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        $relative = $normalizedCandidate.Substring($rootPrefix.Length)
    } else {
        return $false
    }

    return (
        $relative -like 'logs\*' -or
        $relative -like '.godot\*' -or
        $relative -like 'pytest-cache-files-*' -or
        $relative -like 'tests\.tmp*' -or
        $relative -eq 'tests\test_report.json'
    )
}

function Get-DefaultTargets {
    param([string]$Root)

    $seen = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)

    foreach ($candidate in Get-ManagedArtifactCandidates -Root $Root) {
        $fullName = Get-NormalizedPath -Path $candidate
        if (
            (Test-IsManagedRuntimeArtifact -Root $Root -Candidate $fullName) -and
            (Test-RequiresAclRepair -Path $fullName) -and
            $seen.Add($fullName)
        ) {
            $fullName
        }
    }
}

function Get-ManagedArtifactCandidates {
    param([string]$Root)

    $patterns = @(
        (Join-Path $Root 'logs\*'),
        (Join-Path $Root '.godot\*'),
        (Join-Path $Root 'pytest-cache-files-*'),
        (Join-Path $Root 'tests\.tmp*'),
        (Join-Path $Root 'tests\test_report.json')
    )

    foreach ($pattern in $patterns) {
        Get-ChildItem -Force -Path $pattern -ErrorAction SilentlyContinue | ForEach-Object {
            $_.FullName
        }
    }

    foreach ($entry in Get-ChildNamesByCmd -Directory (Join-Path $Root 'logs')) {
        Join-Path $Root "logs\$entry"
    }

    foreach ($entry in Get-ChildNamesByCmd -Directory (Join-Path $Root '.godot')) {
        Join-Path $Root ".godot\$entry"
    }

    foreach ($entry in Get-ChildNamesByCmd -Directory (Join-Path $Root 'tests')) {
        if ($entry -like '.tmp*' -or $entry -eq 'test_report.json') {
            Join-Path $Root "tests\$entry"
        }
    }

    foreach ($entry in Get-ChildNamesByCmd -Directory $Root) {
        if ($entry -like 'pytest-cache-files-*') {
            Join-Path $Root $entry
        }
    }
}

function Get-ChildNamesByCmd {
    param([string]$Directory)

    if (-not (Test-Path -LiteralPath $Directory)) {
        return @()
    }

    $output = & cmd.exe /d /c dir /b /a $Directory 2>$null
    if (-not $output) {
        return @()
    }

    return @(
        $output |
            Where-Object {
                $_
            }
    )
}

function Test-RequiresAclRepair {
    param([string]$Path)

    try {
        Get-ChildItem -Force -LiteralPath $Path -ErrorAction Stop | Out-Null
        return $false
    } catch {
        return $_.Exception.Message -match 'denied'
    }
}

function Get-RepairTargets {
    param(
        [string]$Root,
        [string[]]$ExplicitTargets
    )

    if (-not $ExplicitTargets -or $ExplicitTargets.Count -eq 0) {
        return @(Get-DefaultTargets -Root $Root)
    }

    $resolvedTargets = New-Object System.Collections.Generic.List[string]
    foreach ($target in $ExplicitTargets) {
        $candidate = if ([System.IO.Path]::IsPathRooted($target)) {
            Get-NormalizedPath -Path $target
        } else {
            Get-NormalizedPath -Path (Join-Path $Root $target)
        }

        if (-not (Test-IsManagedRuntimeArtifact -Root $Root -Candidate $candidate)) {
            throw "Refusing to operate on unmanaged path: $candidate"
        }

        $resolvedTargets.Add($candidate) | Out-Null
    }

    return @($resolvedTargets)
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Repair-And-Remove {
    param(
        [string]$Path,
        [switch]$PreviewOnly
    )

    if ($PreviewOnly) {
        $script:RepairState.Preview.Add($Path) | Out-Null
        Write-Output "PREVIEW $Path"
        return
    }

    try {
        & takeown.exe /F $Path /R /D Y | Out-Null
        & icacls.exe $Path /grant '*S-1-5-32-544:(OI)(CI)F' /T /C | Out-Null
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        $script:RepairState.Removed.Add($Path) | Out-Null
        Write-Output "REMOVED $Path"
    } catch {
        $script:RepairState.Failed.Add([pscustomobject]@{
            Path = $Path
            Message = $_.Exception.Message
        }) | Out-Null
        Write-Output "FAILED $Path :: $($_.Exception.Message)"
    }
}

function Write-RepairSummary {
    Write-Output ("SUMMARY preview={0} removed={1} failed={2}" -f `
        $script:RepairState.Preview.Count, `
        $script:RepairState.Removed.Count, `
        $script:RepairState.Failed.Count)

    foreach ($entry in $script:RepairState.Failed) {
        Write-Output "ATTENTION $($entry.Path) :: $($entry.Message)"
    }
}

if (-not $RepoRoot) {
    $RepoRoot = Get-NormalizedPath -Path (Join-Path $PSScriptRoot '..')
} else {
    $RepoRoot = Get-NormalizedPath -Path $RepoRoot
}

$repairTargets = @(Get-RepairTargets -Root $RepoRoot -ExplicitTargets $Targets)
if ($repairTargets.Count -eq 0) {
    Write-Output "NOOP No managed runtime artifacts matched the requested scope."
    return
}

if (-not $Preview -and -not (Test-IsAdministrator)) {
    Write-Warning "Not running in an elevated PowerShell window. ACL repair may fail."
}

foreach ($target in $repairTargets) {
    Repair-And-Remove -Path $target -PreviewOnly:$Preview
}

Write-RepairSummary
