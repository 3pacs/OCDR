param(
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"

function Import-OcdrEnv {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*$' -or $line -match '^\s*#') {
            continue
        }
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
            $key = $matches[1]
            $value = $matches[2].Trim()
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

function Get-ChromePath {
    $candidates = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    return $null
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$envPath = if ([System.IO.Path]::IsPathRooted($EnvFile)) { $EnvFile } else { Join-Path $repoRoot $EnvFile }
Import-OcdrEnv -Path $envPath

$defaultUrls = @(
    "https://www.officeally.com/Logout.aspx?Timeout=1",
    "https://x02.officeally.com/auth0bridge/Logon?ReturnUrl=/secure_oa.asp",
    "https://myservices.optumhealthpaymentservices.com/registrationSignIn.do",
    "https://identity.onehealthcareid.com/oneapp/index.html#/login"
)

$urls = $defaultUrls
if ($env:OCDR_PORTAL_URLS) {
    $urls = $env:OCDR_PORTAL_URLS -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
}

$downloadDir = if ($env:OCDR_PORTAL_DOWNLOAD_DIR) { $env:OCDR_PORTAL_DOWNLOAD_DIR } else { Join-Path $env:USERPROFILE "Downloads" }
$stagingDir = if ($env:OCDR_PORTAL_STAGING_DIR) { $env:OCDR_PORTAL_STAGING_DIR } else { Join-Path $env:USERPROFILE "OCDR-portal-downloads\incoming" }
$stateDir = if ($env:OCDR_PORTAL_STATE_DIR) { $env:OCDR_PORTAL_STATE_DIR } else { Join-Path $env:LOCALAPPDATA "OCMRI\OCDRPortalDownloads" }

New-Item -ItemType Directory -Force -Path $downloadDir, $stagingDir, $stateDir | Out-Null

$chrome = Get-ChromePath
$args = @()
if ($env:OCDR_CHROME_USER_DATA_DIR) {
    $args += "--user-data-dir=$($env:OCDR_CHROME_USER_DATA_DIR)"
}
if ($env:OCDR_CHROME_PROFILE) {
    $args += "--profile-directory=$($env:OCDR_CHROME_PROFILE)"
}
$resetDelaySeconds = 2
if ($env:OCDR_OFFICEALLY_RESET_DELAY_SECONDS) {
    $resetDelaySeconds = [int]$env:OCDR_OFFICEALLY_RESET_DELAY_SECONDS
}

function Open-Urls {
    param(
        [string]$ChromePath,
        [string[]]$BaseArgs,
        [string[]]$TargetUrls
    )

    if ($ChromePath) {
        Start-Process -FilePath $ChromePath -ArgumentList ($BaseArgs + $TargetUrls)
    } else {
        foreach ($url in $TargetUrls) {
            Start-Process $url
        }
    }
}

$officeAllyLogoutFirst = $urls.Count -ge 2 -and $urls[0] -match 'officeally\.com/Logout\.aspx' -and $urls[1] -match 'officeally\.com'
if ($officeAllyLogoutFirst) {
    Open-Urls -ChromePath $chrome -BaseArgs $args -TargetUrls @($urls[0])
    Start-Sleep -Seconds $resetDelaySeconds
    Open-Urls -ChromePath $chrome -BaseArgs $args -TargetUrls $urls[1..($urls.Count - 1)]
} else {
    Open-Urls -ChromePath $chrome -BaseArgs $args -TargetUrls $urls
}

Write-Host "Opened $($urls.Count) portal(s). Download files to: $downloadDir"
Write-Host "After downloads finish, run: python scripts\collect_portal_downloads.py"
