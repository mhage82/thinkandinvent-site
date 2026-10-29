# Run start_annotation.cmd to refresh the image list and open the local website.
[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$siteRoot = $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
& $python (Join-Path $siteRoot 'annotation\prepare_dataset.py')
if ($LASTEXITCODE -ne 0) { throw 'Could not refresh the image list.' }
$expected = Get-Content -LiteralPath (Join-Path $siteRoot 'annotation\data\dataset.json') -Raw | ConvertFrom-Json
# A fresh page URL prevents the browser reusing HTML from an older UI version.
# Saved annotation progress is keyed by study/group/code, so this does not reset it.
$pageVersion = [guid]::NewGuid().ToString('N')
$url = "http://127.0.0.1:$Port/annotation/?v=$pageVersion"
$indexUrl = "http://127.0.0.1:$Port/annotation/data/dataset.json"
function Get-ServedStudyId {
    try {
        $health = (Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/annotation?action=health" -UseBasicParsing -TimeoutSec 2).Content | ConvertFrom-Json
        if ($health.service -ne "annotation-api") { return $null }
        $response = Invoke-WebRequest -Uri $indexUrl -UseBasicParsing -TimeoutSec 2
        return ($response.Content | ConvertFrom-Json).dataset_id
    } catch { return $null }
}
$servedId = Get-ServedStudyId
if (-not $servedId) {
    $listener = [System.Net.Sockets.TcpClient]::new()
    try { $listener.Connect('127.0.0.1', $Port); $occupied = $true }
    catch { $occupied = $false }
    finally { $listener.Dispose() }
    if ($occupied) {
        if ($Port -ge 8010) { throw 'No free preview port found. Use -Port 8020.' }
        & $PSCommandPath -Port ($Port + 1) -NoBrowser:$NoBrowser
        return
    }
    $arguments = @(('"' + (Join-Path $siteRoot 'serve_annotation.py') + '"'), '--port', "$Port")
    $null = Start-Process -FilePath $python -ArgumentList $arguments -WindowStyle Hidden -PassThru
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 250
        $servedId = Get-ServedStudyId
        if ($servedId) { break }
    }
}
if ($servedId -ne $expected.dataset_id) {
    throw "The server at port $Port is not serving this dataset. Run start_annotation.ps1 -Port 8001."
}
Write-Host "Open the annotation website: $url"
if (-not $NoBrowser) { Start-Process $url }
