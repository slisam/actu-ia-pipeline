<#
.SYNOPSIS
Active ou retire la production quotidienne sous le compte Windows courant.
.EXAMPLE
.\scripts\install-task.ps1 -Time '19:00'
.EXAMPLE
.\scripts\install-task.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Time = '19:00',
    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$taskName = 'PipelineIA-Actualites-Quotidien'
$taskPath = '\'
$repositoryPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$description = "PipelineIA daily automation; repository: $repositoryPath"

if ($env:OS -ne 'Windows_NT') { throw 'Le Planificateur de taches necessite Windows.' }
if (-not (Get-Command 'Register-ScheduledTask' -ErrorAction SilentlyContinue)) {
    throw 'Le module ScheduledTasks est indisponible sur cette machine Windows.'
}
$existingTask = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue
if ($existingTask -and $existingTask.Description -ne $description) {
    throw "La tache $taskName existe pour un autre emplacement. Inspectez-la dans le Planificateur avant de continuer."
}
if ($Uninstall) {
    if ($existingTask) {
        Unregister-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Confirm:$false
        Write-Host 'La tache quotidienne PipelineIA a ete retiree. Les fichiers et connexions sont conserves.'
    }
    else { Write-Host 'Aucune tache quotidienne PipelineIA n est active.' }
    return
}

$pythonPath = Join-Path $repositoryPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'Executez scripts\setup.ps1 avant de programmer la production quotidienne.'
}
$timezone = Get-TimeZone
if ($timezone.Id -notin @('Romance Standard Time', 'Europe/Paris')) {
    throw "Le fuseau Windows est '$($timezone.Id)'. Reglez le fuseau de Windows sur Paris pour que $Time corresponde a l heure de Paris, puis relancez."
}
$hour, $minute = $Time.Split(':')
$startTime = [DateTime]::Today.AddHours([int]$hour).AddMinutes([int]$minute)
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument '-m pipelineia run --publish' -WorkingDirectory $repositoryPath
$trigger = New-ScheduledTaskTrigger -Daily -At $startTime
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $description
Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -InputObject $task -Force | Out-Null
Write-Host "Production quotidienne activee a $Time, heure de Paris, sous $currentUser."
Write-Host 'Le PC doit etre allume, connecte a Internet, et votre session Windows ouverte.'
Write-Host 'La publication depend des plateformes activees dans config.yaml et de leurs connexions.'
Write-Host 'Pour retirer uniquement cette tache : .\scripts\install-task.ps1 -Uninstall'
