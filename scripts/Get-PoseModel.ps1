$ErrorActionPreference = 'Stop'
$modelDir = Join-Path $PSScriptRoot '../models'
$model = Join-Path $modelDir 'pose_landmarker_lite.task'
$sha256 = '59929E1D1EE95287735DDD833B19CF4AC46D29BC7AFDDBBF6753C459690D574A'

if (Test-Path -LiteralPath $model -PathType Leaf) {
    if ((Get-FileHash -LiteralPath $model).Hash -ne $sha256) {
        throw "The existing model has the wrong checksum. Move it out of $modelDir and run this script again."
    }
    Write-Output $model
    return
}

New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
$download = Join-Path $modelDir ([System.IO.Path]::GetRandomFileName())
try {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task' -OutFile $download
    if ((Get-FileHash -LiteralPath $download).Hash -ne $sha256) {
        throw 'Downloaded model checksum did not match.'
    }
    Move-Item -LiteralPath $download -Destination $model
    Write-Output $model
} finally {
    if (Test-Path -LiteralPath $download) { Remove-Item -LiteralPath $download }
}
