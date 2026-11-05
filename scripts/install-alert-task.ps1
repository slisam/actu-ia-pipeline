<# Planifie uniquement l'envoi des alertes en attente ; aucune generation video. #>
[CmdletBinding()]
param([switch]$Uninstall)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskName = 'PipelineIA-Alertes'
$description = "PipelineIA alert delivery; repository: $repositoryPath"
if ($env:OS -ne 'Windows_NT') { throw 'Ce script necessite Windows.' }
$existingTask = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
if ($existingTask -and $existingTask.Description -ne $description) {
    throw 'Une tache d alertes existe pour un autre dossier. Verifiez son emplacement avant de continuer.'
}
if ($Uninstall) {
    if ($existingTask) { Unregister-ScheduledTask -TaskName $taskName -TaskPath '\' -Confirm:$false }
    return
}
$pythonPath = Join-Path $repositoryPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw 'Lancez scripts\setup.ps1 avant la planification.' }
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument '-m pipelineia alerts-flush' -WorkingDirectory $repositoryPath
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 5)
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $description
Register-ScheduledTask -TaskName $taskName -TaskPath '\' -InputObject $task -Force | Out-Null
Write-Host 'Relance des alertes planifiee toutes les cinq minutes, sans generation de video.'
Write-Host 'Le PC doit etre allume et la session Windows ouverte.'
