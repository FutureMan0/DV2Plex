$BasePath = $PSScriptRoot
$RepositoryPath = "$BasePath\."

# NOTE: Windows-classic-samples is supposed to be a cloned repository in sibling directory, 
#       we are interested in branch "directshow" with the actual DirectShow and BaseClasses code.
#       BaseClasses are assumed to be built there and we just import the pre-built static libraries
#       here to track them in this repository and expose detached from huge repository with samples.
#       See https://github.com/roman380/Windows-classic-samples/tree/directshow/Samples/Win7Samples/multimedia/directshow

$SourcePath = "$RepositoryPath\..\Windows-classic-samples\Samples\Win7Samples\multimedia\directshow"

Copy-Item "$SourcePath\baseclasses" "$RepositoryPath" -Recurse -Force

if (!(Test-Path "$RepositoryPath\bin")) {
    New-Item -Path $RepositoryPath -Name "bin" -ItemType Directory
}

$Platforms = "Win32", "x64"
$Configurations = "Debug", "Release"

$Platforms | ForEach-Object {
    $Platform = $_
    if (!(Test-Path "$RepositoryPath\bin\$Platform")) {
        New-Item -Path "$RepositoryPath\bin" -Name $Platform -ItemType Directory
    }
    $Configurations | ForEach-Object {
        $Configuration = $_
        if (!(Test-Path "$RepositoryPath\bin\$Platform\$Configuration")) {
            New-Item -Path "$RepositoryPath\bin\$Platform" -Name $Configuration -ItemType Directory
        }
        "BaseClasses.lib", "BaseClasses.pdb" | ForEach-Object {
            Copy-Item "$SourcePath\bin\$Platform\$Configuration\$_" "$RepositoryPath\bin\$Platform\$Configuration" -Force
        }
    }
}

Start-Process "git" -ArgumentList "log -16 --pretty=""%H""" -PassThru -Wait -NoNewWindow -WorkingDirectory $SourcePath -RedirectStandardOutput "$RepositoryPath\git-log-import.txt"
