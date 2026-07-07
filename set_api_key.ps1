$ErrorActionPreference = "Stop"

function ConvertFrom-SecureInput {
    param([System.Security.SecureString]$Secure)
    if ($null -eq $Secure) {
        return ""
    }
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        if ($ptr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        }
    }
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $root ".env"

Write-Host "[INFO] API key will be saved to this project's .env only."
Write-Host "[INFO] Input is hidden. Press Enter on an empty field to keep existing key."
Write-Host ""

$deepseek = ConvertFrom-SecureInput (Read-Host "DeepSeek/OpenAI-compatible API Key" -AsSecureString)

$lines = @()
if (Test-Path $envPath) {
    $lines = Get-Content -LiteralPath $envPath -Encoding UTF8 |
        Where-Object { $_ -notmatch '^\s*DEEPSEEK_API_KEY\s*=' }
}

if (-not [string]::IsNullOrWhiteSpace($deepseek)) {
    $lines += "DEEPSEEK_API_KEY=$deepseek"
}
elseif (Test-Path $envPath) {
    $old = Get-Content -LiteralPath $envPath -Encoding UTF8 |
        Where-Object { $_ -match '^\s*DEEPSEEK_API_KEY\s*=' } |
        Select-Object -First 1
    if ($old) {
        $lines += $old
    }
}

if ($lines.Count -eq 0) {
    Write-Host "[WARN] No key entered and .env has no other entries. Nothing changed."
    exit 0
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($envPath, [string[]]$lines, $utf8NoBom)

Write-Host "[OK] Saved keys to $envPath"
Write-Host "[INFO] You can now run check_ai.bat or run_clipboard.bat."
