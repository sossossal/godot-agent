[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$SourcePath,
    [switch]$SkipDistribution,
    [switch]$SkipSandbox,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-RepoPath {
    param(
        [string]$Root,
        [string]$RelativePath
    )

    return (Resolve-Path (Join-Path $Root $RelativePath)).Path
}

function Ensure-Directory {
    param([string]$PathValue)

    if (-not (Test-Path $PathValue)) {
        New-Item -ItemType Directory -Force -Path $PathValue | Out-Null
    }
}

function Get-FileHashMap {
    param([string]$DirectoryPath)

    $result = @{}
    if (-not (Test-Path $DirectoryPath)) {
        return $result
    }

    $root = (Resolve-Path $DirectoryPath).Path
    Get-ChildItem -LiteralPath $root -File -Recurse | ForEach-Object {
        $relative = $_.FullName.Substring($root.Length).TrimStart('\').Replace('\', '/')
        $result[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }

    return $result
}

function Test-DirectoryMatch {
    param(
        [string]$SourceDir,
        [string]$TargetDir
    )

    if (-not (Test-Path $TargetDir)) {
        return $false
    }

    $sourceMap = Get-FileHashMap -DirectoryPath $SourceDir
    $targetMap = Get-FileHashMap -DirectoryPath $TargetDir

    if ($sourceMap.Count -ne $targetMap.Count) {
        return $false
    }

    foreach ($key in $sourceMap.Keys) {
        if (-not $targetMap.ContainsKey($key)) {
            return $false
        }
        if ($targetMap[$key] -ne $sourceMap[$key]) {
            return $false
        }
    }

    return $true
}

function Sync-Directory {
    param(
        [string]$SourceDir,
        [string]$TargetDir
    )

    Ensure-Directory -PathValue $TargetDir

    Get-ChildItem -LiteralPath $TargetDir -Force -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
    }

    Copy-Item -Path (Join-Path $SourceDir '*') -Destination $TargetDir -Recurse -Force
}

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

if (-not $SourcePath) {
    $SourcePath = Join-Path $RepoRoot "addons\godot_agent"
} else {
    $SourcePath = (Resolve-Path $SourcePath).Path
}

if (-not (Test-Path $SourcePath)) {
    throw "Plugin source not found: $SourcePath"
}

$targets = @()
if (-not $SkipDistribution) {
    $targets += [pscustomobject]@{
        Name = "distribution"
        Path = Join-Path $RepoRoot "godot_plugin\addons\godot_agent"
    }
}
if (-not $SkipSandbox) {
    $targets += [pscustomobject]@{
        Name = "sandbox"
        Path = Join-Path $RepoRoot "sandbox_project\addons\godot_agent"
    }
}

$results = @()
foreach ($target in $targets) {
    $matches = Test-DirectoryMatch -SourceDir $SourcePath -TargetDir $target.Path
    $changed = $false

    if (-not $CheckOnly -and -not $matches) {
        $changed = $true
        Sync-Directory -SourceDir $SourcePath -TargetDir $target.Path
        $matches = Test-DirectoryMatch -SourceDir $SourcePath -TargetDir $target.Path
    }

    $results += [ordered]@{
        name = $target.Name
        path = $target.Path
        synced = $matches
        changed = $changed
    }
}

[ordered]@{
    ok = @($results | Where-Object { -not $_.synced }).Count -eq 0
    source = $SourcePath
    check_only = [bool]$CheckOnly
    targets = $results
} | ConvertTo-Json -Depth 5
