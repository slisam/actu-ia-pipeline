<#
.SYNOPSIS
Prepare Python et, sur demande, le client officiel Gemini CLI sur Windows.
.EXAMPLE
.\scripts\setup.ps1 -Login
#>
[CmdletBinding()]
param(
    [string]$PythonExe = 'python',
    [ValidateSet('gemini_browser', 'gemini_cli')]
    [string]$Provider = 'gemini_browser',
    [switch]$InstallGemini,
    [switch]$Login
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$requirementsPath = Join-Path $repositoryPath 'requirements.txt'
$venvPython = Join-Path $repositoryPath '.venv\Scripts\python.exe'
if ($InstallGemini -and -not $PSBoundParameters.ContainsKey('Provider')) {
    $Provider = 'gemini_cli'
}
if ($InstallGemini -and $Provider -ne 'gemini_cli') {
    throw '-InstallGemini concerne uniquement -Provider gemini_cli.'
}

if ($env:OS -ne 'Windows_NT') {
    throw 'Ce script est reserve a Windows.'
}
if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
    throw 'requirements.txt est introuvable. Executez ce script depuis une copie complete du depot.'
}

$pythonCommand = Get-Command -Name $PythonExe -CommandType Application -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw 'Python est introuvable. Installez Python 3.11 ou plus recent, puis relancez le script.'
}
$versionText = & $pythonCommand.Source -c 'import sys; print(str(sys.version_info.major) + "." + str(sys.version_info.minor))'
if ($LASTEXITCODE -ne 0 -or [version]$versionText -lt [version]'3.11') {
    throw 'Python 3.11 ou plus recent est necessaire.'
}
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Write-Host 'Creation de l environnement Python local...'
    & $pythonCommand.Source -m venv (Join-Path $repositoryPath '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'La creation de l environnement Python a echoue.' }
}
Write-Host 'Installation des bibliotheques de production...'
& $venvPython -m pip --disable-pip-version-check install -r $requirementsPath
if ($LASTEXITCODE -ne 0) { throw 'L installation des bibliotheques Python a echoue.' }

$geminiCommand = Get-Command -Name 'gemini.cmd' -CommandType Application -ErrorAction SilentlyContinue
if ($Provider -eq 'gemini_cli' -and ($InstallGemini -or $Login -or $geminiCommand)) {
    $nodeCommand = Get-Command -Name 'node.exe' -CommandType Application -ErrorAction SilentlyContinue
    if (-not $nodeCommand) {
        throw 'Installez Node.js LTS 22 ou plus recent depuis https://nodejs.org/ puis relancez ce script.'
    }
    $nodeVersion = & $nodeCommand.Source --version
    if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v?(\d+)\.' -or [int]$Matches[1] -lt 22) {
        throw 'Ce projet utilise Node.js 22 ou plus recent. Installez une version LTS prise en charge.'
    }
}
if ($InstallGemini) {
    $npmCommand = Get-Command -Name 'npm.cmd' -CommandType Application -ErrorAction SilentlyContinue
    if (-not $npmCommand) { throw 'npm.cmd est introuvable. Reinstallez Node.js LTS avec npm.' }
    Write-Host 'Installation du paquet officiel @google/gemini-cli...'
    & $npmCommand.Source install -g '@google/gemini-cli'
    if ($LASTEXITCODE -ne 0) { throw 'L installation de Gemini CLI a echoue.' }
    $geminiCommand = Get-Command -Name 'gemini.cmd' -CommandType Application -ErrorAction SilentlyContinue
    if (-not $geminiCommand) {
        $npmPrefix = (& $npmCommand.Source prefix -g | Select-Object -Last 1).Trim()
        $candidatePath = Join-Path $npmPrefix 'gemini.cmd'
        if (Test-Path -LiteralPath $candidatePath -PathType Leaf) {
            throw "Gemini est installe dans $npmPrefix. Ajoutez ce dossier au PATH utilisateur, ouvrez une nouvelle fenetre PowerShell, puis relancez setup.ps1 -Login."
        }
        throw 'Gemini CLI reste introuvable apres installation. Verifiez le dossier global npm et le PATH utilisateur.'
    }
}

if ($Login -and $Provider -eq 'gemini_browser') {
    Write-Host 'Connexion Google dans un profil Edge separe, reserve au pipeline.'
    Write-Host 'Choisissez votre compte Google AI Pro. Aucun mot de passe ne sera copie dans le depot.'
    Push-Location -LiteralPath $repositoryPath
    try {
        & $venvPython -m pipelineia.browser login --config (Join-Path $repositoryPath 'config.yaml')
        if ($LASTEXITCODE -ne 0) { throw 'La connexion navigateur a ete interrompue ou a echoue.' }
    }
    finally { Pop-Location }
}
if ($Login -and $Provider -eq 'gemini_cli') {
    if (-not $geminiCommand) {
        throw 'Gemini CLI est introuvable. Relancez avec -InstallGemini -Login.'
    }
    Write-Host 'Dans Gemini, choisissez Sign in with Google et le compte de votre abonnement Google AI Pro.'
    Write-Host 'Apres la connexion, quittez Gemini avec /quit pour terminer la preparation.'
    # Ce processus de connexion ne doit pas reutiliser une cle API ou Vertex AI.
    $authVariableNames = @('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_GENAI_USE_VERTEXAI')
    $savedAuthValues = @{}
    foreach ($variableName in $authVariableNames) {
        $savedAuthValues[$variableName] = [Environment]::GetEnvironmentVariable($variableName, 'Process')
        [Environment]::SetEnvironmentVariable($variableName, $null, 'Process')
    }
    try {
        Push-Location -LiteralPath $repositoryPath
        try { & $geminiCommand.Source }
        finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { throw 'La connexion Gemini a ete interrompue ou a echoue.' }
    }
    finally {
        foreach ($variableName in $authVariableNames) {
            [Environment]::SetEnvironmentVariable($variableName, $savedAuthValues[$variableName], 'Process')
        }
    }
}

if ($Provider -eq 'gemini_cli' -and -not $geminiCommand) {
    Write-Warning 'Python est pret. Pour le compte Google AI Pro, relancez .\scripts\setup.ps1 -InstallGemini -Login.'
}
if ($Provider -eq 'gemini_cli') {
    Write-Warning 'Google peut refuser Gemini CLI avec UNSUPPORTED_CLIENT pour le compte connecte. Aucun acces Pro par CLI n est garanti.'
}
Write-Host 'Preparation terminee. Diagnostic : .\.venv\Scripts\python.exe -m pipelineia doctor'
Write-Host 'Aucune tache quotidienne ni publication n a ete activee par ce script.'
