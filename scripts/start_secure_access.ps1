param([ValidateRange(1024, 65535)][int]$Port = 19119)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$knownHosts = Join-Path $repoRoot 'deploy/hermes/known_hosts'
$sshPath = Join-Path $env:WINDIR 'System32/OpenSSH/ssh.exe'
$outputDir = Join-Path $repoRoot '.build'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$sshArgs = @('-N', '-l', 'ubuntu', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
    '-o', 'StrictHostKeyChecking=yes', '-o', "UserKnownHostsFile=`"$knownHosts`"",
    '-o', 'ServerAliveInterval=20', '-o', 'ServerAliveCountMax=3',
    '-L', "127.0.0.1:${Port}:127.0.0.1:9119", 'haudi-hermes-server')
$process = Start-Process -FilePath $sshPath -ArgumentList $sshArgs -WindowStyle Hidden -PassThru `
    -RedirectStandardError (Join-Path $outputDir 'secure-access.log')
Start-Sleep -Seconds 2
if ($process.HasExited) { throw 'SSH tunnel failed. Check .build/secure-access.log and the configured SSH alias.' }
$process.Id | Set-Content -LiteralPath (Join-Path $outputDir 'secure-access.pid')
Write-Output "Secure SSH access ready: http://localhost:$Port (SSH process $($process.Id))"
