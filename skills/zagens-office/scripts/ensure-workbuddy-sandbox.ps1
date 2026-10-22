# Idempotent WorkBuddy sandbox whitelist for ~/.zagens-pro.
# Mirrors crates/office-cli/src/integrate/workbuddy.rs (Windows-first).
# Does not overwrite skills; only touches sandbox.extraAllowWrite.

$ErrorActionPreference = 'Stop'

$entry = '~/.zagens-pro'
$userHome = if ($env:USERPROFILE) { $env:USERPROFILE } elseif ($env:HOME) { $env:HOME } else { $null }

function Write-Result {
    param(
        [bool]$Ok,
        [string]$Status,
        [string]$Path,
        [string]$Message
    )
    $payload = [ordered]@{
        ok      = $Ok
        status  = $Status
        path    = $Path
        message = $Message
    }
    $payload | ConvertTo-Json -Compress
}

if (-not $userHome) {
    Write-Result -Ok $false -Status 'error' -Path '' -Message 'USERPROFILE/HOME not set'
    exit 1
}

$settingsPath = Join-Path $userHome '.workbuddy\settings.json'
if (-not (Test-Path -LiteralPath $settingsPath)) {
    Write-Result -Ok $true -Status 'skipped' -Path $settingsPath -Message 'WorkBuddy settings.json not found; open WorkBuddy once, then re-run'
    exit 0
}

try {
    $raw = [System.IO.File]::ReadAllText($settingsPath)
    if ([string]::IsNullOrWhiteSpace($raw)) {
        Write-Result -Ok $false -Status 'error' -Path $settingsPath -Message 'settings.json is empty'
        exit 1
    }

    $settings = $raw | ConvertFrom-Json
    if ($null -eq $settings -or $settings -is [System.Object[]]) {
        Write-Result -Ok $false -Status 'error' -Path $settingsPath -Message 'settings.json root must be an object'
        exit 1
    }

    if (-not $settings.PSObject.Properties['sandbox'] -or $null -eq $settings.sandbox) {
        $settings | Add-Member -NotePropertyName sandbox -NotePropertyValue ([pscustomobject]@{}) -Force
    }
    if (-not $settings.sandbox.PSObject.Properties['extraAllowWrite'] -or $null -eq $settings.sandbox.extraAllowWrite) {
        $settings.sandbox | Add-Member -NotePropertyName extraAllowWrite -NotePropertyValue @() -Force
    }

    $allow = @($settings.sandbox.extraAllowWrite)
    if ($allow -contains $entry) {
        Write-Result -Ok $true -Status 'already' -Path $settingsPath -Message "sandbox.extraAllowWrite already contains $entry"
        exit 0
    }

    $stamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $backup = Join-Path (Split-Path -Parent $settingsPath) "settings.json.bak-zagens-$stamp"
    Copy-Item -LiteralPath $settingsPath -Destination $backup -Force

    $settings.sandbox.extraAllowWrite = @($allow + $entry)
    $json = $settings | ConvertTo-Json -Depth 20
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($settingsPath, $json + "`n", $utf8NoBom)

    Write-Result -Ok $true -Status 'added' -Path $settingsPath -Message "added $entry (backup $backup)"
    exit 0
}
catch {
    Write-Result -Ok $false -Status 'error' -Path $settingsPath -Message $_.Exception.Message
    exit 1
}
