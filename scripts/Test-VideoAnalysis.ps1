param(
    [Parameter(Mandatory = $true)][string]$Video,
    [ValidateSet('left', 'right')][string]$LeadArm = 'left',
    [ValidateSet('mock', 'vllm')][string]$Backend = 'vllm',
    [ValidateRange(1, 65535)][int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$file = Get-Item -LiteralPath $Video
$mime = switch ($file.Extension.ToLowerInvariant()) {
    '.mp4' { 'video/mp4' }
    '.webm' { 'video/webm' }
    default { throw 'Choose an MP4 or WebM clip.' }
}
$session = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/api/sessions" `
    -ContentType 'application/json' -Body (@{
        station_id = 'demo-station'; consent = $true; lead_arm = $LeadArm
    } | ConvertTo-Json -Compress)
$url = "http://127.0.0.1:$Port/api/sessions/$($session.session_id)"
$headers = @{ 'X-Session-Token' = $session.session_token }
try {
    $uploaded = curl.exe --fail --silent --show-error -H "X-Session-Token: $($session.session_token)" `
        -F "video=@`"$($file.FullName)`";type=$mime" "$url/video"
    if ($LASTEXITCODE -ne 0 -or ($uploaded | ConvertFrom-Json).status -ne 'queued') {
        throw 'Upload did not enter the processing queue.'
    }
    $deadline = (Get-Date).AddMinutes(2)
    do {
        $job = Invoke-RestMethod -Uri $url -Headers $headers
        if ($job.status -in 'completed', 'failed') { break }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    $job.result | ConvertTo-Json -Depth 5
    if ($job.status -ne 'completed' -or $job.result.analysis_type -ne 'experimental_pose_extension_v1' `
        -or $job.result.decoded_frames -le 0 -or $job.result.technique_analyzed -ne $false `
        -or $job.result.feedback_status -ne 'generated_unreviewed' `
        -or $job.result.feedback_backend -ne $Backend -or -not $job.result.experimental_feedback) {
        throw "Video analysis or $Backend feedback did not complete as expected (job status: $($job.status))."
    }
} finally {
    Invoke-RestMethod -Method Delete -Uri $url -Headers $headers | Out-Null
}
