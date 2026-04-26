[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$SkillName = "closure-first-engineer",
    [string]$DestinationRoot,
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Ensure-Directory {
    param([string]$PathValue)

    if (-not (Test-Path -LiteralPath $PathValue)) {
        New-Item -ItemType Directory -Force -Path $PathValue | Out-Null
    }
}

function Get-FileHashMap {
    param([string]$DirectoryPath)

    $result = @{}
    if (-not (Test-Path -LiteralPath $DirectoryPath)) {
        return $result
    }

    $root = (Resolve-Path -LiteralPath $DirectoryPath).Path
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

    if (-not (Test-Path -LiteralPath $TargetDir)) {
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
    $RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
}

if (-not $DestinationRoot) {
    $DestinationRoot = Join-Path $HOME ".codex\skills"
}

$SourcePath = Join-Path $RepoRoot ".codex\skills\$SkillName"
$TargetPath = Join-Path $DestinationRoot $SkillName
$SkillFile = Join-Path $SourcePath "SKILL.md"

if (-not (Test-Path -LiteralPath $SkillFile)) {
    throw "Skill package not found: $SkillFile"
}

$alreadySynced = Test-DirectoryMatch -SourceDir $SourcePath -TargetDir $TargetPath
$changed = $false

if (-not $Preview -and -not $alreadySynced) {
    $changed = $true
    Sync-Directory -SourceDir $SourcePath -TargetDir $TargetPath
    $alreadySynced = Test-DirectoryMatch -SourceDir $SourcePath -TargetDir $TargetPath
}

[ordered]@{
    ok = $alreadySynced
    preview = [bool]$Preview
    skill = $SkillName
    source = $SourcePath
    destination = $TargetPath
    changed = $changed
} | ConvertTo-Json -Depth 4
