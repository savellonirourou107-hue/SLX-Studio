param([string]$Installer = (Join-Path $PSScriptRoot '..\dist-installer\SLX-Studio-2-Setup-x64.exe'))
$ErrorActionPreference = 'Stop'
$taskTempRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$taskDirectory = Join-Path $taskTempRoot ('slx-install-test-' + [Guid]::NewGuid().ToString('N'))
$taskInstallPath = Join-Path $taskDirectory 'installed'
$taskInstallerPath = (Resolve-Path -LiteralPath $Installer).Path
[void](New-Item -ItemType Directory -Path $taskDirectory)
$previousExecutable = $env:SLX_DESKTOP_PACKAGED_EXE
try {
    $installArgs = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/DIR=`"$taskInstallPath`"", "/LOG=`"$(Join-Path $taskDirectory 'install.log')`"")
    $setup = Start-Process -FilePath $taskInstallerPath -ArgumentList $installArgs -Wait -PassThru -WindowStyle Hidden
    if ($setup.ExitCode -ne 0) { throw "Installer failed with exit code $($setup.ExitCode)" }
    foreach ($relative in @('SLXStudio.exe', 'resources\app\electron\main.cjs', 'resources\app\src\slxdiff\rpc.py', 'resources\app\extensions\sample.hello\extension.mjs', 'unins000.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $taskInstallPath $relative) -PathType Leaf)) { throw "Installed asset missing: $relative" }
    }
    $env:SLX_DESKTOP_PACKAGED_EXE = Join-Path $taskInstallPath 'SLXStudio.exe'
    & node (Join-Path $PSScriptRoot 'test-packaged-electron.mjs')
    if ($LASTEXITCODE -ne 0) { throw "Installed application smoke test failed: $LASTEXITCODE" }
} finally {
    $env:SLX_DESKTOP_PACKAGED_EXE = $previousExecutable
    $uninstaller = Join-Path $taskInstallPath 'unins000.exe'
    if (Test-Path -LiteralPath $uninstaller -PathType Leaf) {
        $uninstallArgs = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$(Join-Path $taskDirectory 'uninstall.log')`"")
        $uninstall = Start-Process -FilePath $uninstaller -ArgumentList $uninstallArgs -Wait -PassThru -WindowStyle Hidden
        if ($uninstall.ExitCode -ne 0) { throw "Uninstaller failed with exit code $($uninstall.ExitCode)" }
        if (Test-Path -LiteralPath $taskInstallPath) { throw "Uninstall left installed files at $taskInstallPath" }
        $uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{B90526D0-8A9C-4C45-8C3C-6F6CE1D4AA20}_is1'
        if (Test-Path -LiteralPath $uninstallKey) { throw 'Uninstall registry entry was not removed' }
    }
    Write-Output "Installer test logs: $taskDirectory"
}
Write-Output 'PASS: Windows installer installs required assets, launches/saves/reopens, and uninstalls cleanly.'
