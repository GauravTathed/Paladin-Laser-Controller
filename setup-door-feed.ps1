param([string]$PiAddress)

$ErrorActionPreference = 'Stop'

$config = Join-Path $env:LOCALAPPDATA 'QuDitPaladin'
$key = Join-Path $config 'shutter_ed25519'
$knownHosts = Join-Path $config 'known_hosts'
$bootstrapConfig = Join-Path $config 'setup-ssh.conf'
$ssh = (Get-Command ssh.exe).Source
$keygen = (Get-Command ssh-keygen.exe).Source
if (-not $PiAddress -and (Test-Path -LiteralPath $bootstrapConfig)) {
    $existingAddress = Select-String -LiteralPath $bootstrapConfig -Pattern '^\s+HostName\s+(\S+)\s*$' | Select-Object -First 1
    if ($existingAddress) { $PiAddress = $existingAddress.Matches[0].Groups[1].Value }
}
$addressLine = ''
if ($PiAddress) {
    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($PiAddress, [ref]$parsed)) { throw 'PiAddress must be an IP address.' }
    $addressLine = "    HostName $parsed"
}
New-Item -ItemType Directory -Path $config -Force | Out-Null
Set-Content -LiteralPath $knownHosts -Encoding ascii -Value 'welcome-pi.local ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA8oxp2Qx6i9tvsjCFYOdHvg6cp1mKdxTj08tl65qVZL'
$knownHostsForSSH = $knownHosts.Replace('\', '/')
$configuration = @"
Host welcome-pi.local
$addressLine
    HostKeyAlias welcome-pi.local
    User pi
    StrictHostKeyChecking yes
    UserKnownHostsFile "$knownHostsForSSH"
    HostKeyAlgorithms ssh-ed25519
    ConnectTimeout 5
"@
# Windows PowerShell's UTF-8 encoding emits a BOM, which OpenSSH rejects.
[IO.File]::WriteAllText($bootstrapConfig, $configuration, [Text.UTF8Encoding]::new($false))
if (-not (Test-Path -LiteralPath $key)) {
    $generated = Start-Process -FilePath $keygen -ArgumentList ('-q -t ed25519 -N "" -C qudit-paladin-shutter -f "' + $key + '"') -NoNewWindow -Wait -PassThru
    if ($generated.ExitCode -ne 0) { throw 'Could not generate the shutter feed key.' }
}
$publicKey = ((& $keygen -y -f $key) -split ' ' | Select-Object -First 2) -join ' '
if ($LASTEXITCODE -ne 0 -or $publicKey -cnotmatch '^ssh-ed25519 [A-Za-z0-9+/]+=*$') { throw 'Could not read the shutter feed public key.' }

Write-Host 'Enter the Pi account password if prompted to register the shutter feed key.'
$register = @'
set -eu
cd "$HOME"
test -f lab-status-display/paladin_shutter.py
umask 077
mkdir -p .ssh
touch .ssh/authorized_keys
chmod 600 .ssh/authorized_keys
line='restrict,command="/usr/bin/python3 -B /home/pi/lab-status-display/paladin_shutter.py" __KEY__ qudit-paladin-shutter'
if ! grep -Fxq -- "$line" .ssh/authorized_keys; then
    if grep -q ' qudit-paladin-shutter$' .ssh/authorized_keys; then
        echo 'A different Paladin feed key is already registered. Ask the Pi administrator to replace it.' >&2
        exit 1
    fi
    printf '%s\n' "$line" >> .ssh/authorized_keys
fi
'@
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($register.Replace('__KEY__', $publicKey) -replace "`r", "")))
& $ssh -F $bootstrapConfig -T welcome-pi.local "printf '%s' '$encoded' | base64 -d | bash"
if ($LASTEXITCODE -ne 0) { throw 'Could not register the shutter feed key.' }

$result = 'probe' | & $ssh -F $bootstrapConfig -T -i $key -o 'IdentitiesOnly=yes' -o 'BatchMode=yes' welcome-pi.local shutter-status
if ($LASTEXITCODE -ne 0 -or $result -ne 'OK') { throw 'The Pi did not acknowledge the shutter status test.' }
Write-Host 'Pi connection verified. Launch the updated PaladinLaserController.exe and connect to the real COM port as usual.'
