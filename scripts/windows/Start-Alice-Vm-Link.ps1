<#
.SYNOPSIS
  Exposes Windows LM Studio only on Ubuntu VM loopback through SSH.
.DESCRIPTION
  Starts LM Studio on loopback. KeepAlive reconnects after VM restarts.
  StartVm starts a powered-off VM once, when this script starts.
#>
[CmdletBinding()]
param(
  [string]$VmUser = 'eva2',
  [int]$SshPort = 2222,
  [int]$LmStudioPort = 1234,
  [string]$KeyPath = (Join-Path $env:USERPROFILE '.ssh\alice_vm_ed25519'),
  [switch]$KeepAlive,
  [switch]$StartVm
)
$ErrorActionPreference = 'Stop'
$lmsPath = Join-Path $env:USERPROFILE '.lmstudio\bin\lms.exe'
if (-not (Test-Path -LiteralPath $lmsPath)) { throw "No encuentro LM Studio CLI: $lmsPath" }
if (-not (Test-Path -LiteralPath $KeyPath)) { throw "No encuentro la llave: $KeyPath" }
if ($StartVm) {
  $vboxPath = Join-Path $env:ProgramFiles 'Oracle\VirtualBox\VBoxManage.exe'
  if (-not (Test-Path -LiteralPath $vboxPath)) { throw 'No encuentro Oracle VirtualBox.' }
  $vmInfo = & $vboxPath showvminfo ALICE --machinereadable
  if ($LASTEXITCODE -ne 0) { throw 'No encuentro la VM ALICE.' }
  if ($vmInfo -match '^VMState="poweroff"$') {
    & $vboxPath startvm ALICE --type headless
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo iniciar la VM ALICE.' }
  }
}
do {
  & $lmsPath server start --port $LmStudioPort --bind 127.0.0.1
  if ($LASTEXITCODE -eq 0) {
    & ssh -N -T -i $KeyPath -p $SshPort -o IdentitiesOnly=yes -o BatchMode=yes `
      -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes -o ConnectTimeout=8 `
      -o ServerAliveInterval=20 -o ServerAliveCountMax=3 `
      -R "127.0.0.1:${LmStudioPort}:127.0.0.1:${LmStudioPort}" "$VmUser@127.0.0.1"
  }
  if (-not $KeepAlive) {
    if ($LASTEXITCODE -ne 0) { throw "El enlace terminó con código $LASTEXITCODE" }
    break
  }
  Start-Sleep -Seconds 15
} while ($KeepAlive)
