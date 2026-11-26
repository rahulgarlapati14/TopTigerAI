# Video pose analysis on Windows

From the repository root, with Docker Desktop running Linux containers, fetch and verify Google's versioned [MediaPipe Pose Landmarker Lite model](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker).

```powershell
.\scripts\Get-PoseModel.ps1
```

The script verifies SHA-256 before installing the asset. Compose mounts only the model file, read-only, into the worker. Keep the file in `models\pose_landmarker_lite.task`. Uploaded videos stay in the local Compose video volume shared by the API and worker. The gateway receives only bounded pose statistics, and the model prompt excludes free-text notes.

## Start with NVIDIA GPU feedback

Use Docker Desktop's WSL 2 backend and a working NVIDIA GPU setup. The final overlay applies the existing low-VRAM settings for the RTX 4050/4060.

```powershell
$compose = @('-f', 'docker-compose.yml', '-f', 'docker-compose.pose.yml',
             '-f', 'deploy/gpu/docker-compose.gpu.yml', '-f', 'deploy/gpu/docker-compose.rtx4050.yml')
docker compose @compose up -d --build
Invoke-RestMethod http://127.0.0.1:8001/health/ready
```

Wait for `status = ready` and `backend = vllm` before uploading. If the endpoint returns 503 while the weights load, check `docker compose @compose logs vllm inference-gateway` and try readiness again. The vLLM container stays on the internal Docker network.

## Start with CPU-only demo feedback

```powershell
docker compose -f docker-compose.yml -f docker-compose.pose.yml up -d --build
Invoke-RestMethod http://127.0.0.1:8001/health/ready
```

Readiness should report `backend = mock`. Both setups use CPU pose extraction.

## Verify an upload

Open the [local station](http://127.0.0.1:8000), choose the lead arm and upload a consenting adult's solo MP4 or WebM clip under 30 seconds and 25 MB. The station shows pose visibility, candidate extension-and-return cycles when measurable, and an unreviewed filming tip. Low visibility suppresses the movement count. If the gateway is unavailable, the pose results still appear. Use the station's delete button to remove the session and video.

For a repeatable check through the real API, worker and gateway, run the following. Use `-Backend mock` for CPU-only demo feedback. The script removes its test session on exit.

```powershell
.\scripts\Test-VideoAnalysis.ps1 -Video 'C:\path\to\clip.mp4' -LeadArm left -Backend vllm
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
```

The smoke test verifies decoding, stored pose results and feedback from the requested backend. It allows a low-visibility result, so check `quality` and `usable_frame_fraction` when evaluating a clearly framed clip. It does not measure boxing technique accuracy.
