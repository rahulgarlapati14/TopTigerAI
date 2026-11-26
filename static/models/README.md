# TopTiger 3D mascot asset

The web homepage loads `/static/models/base.glb` using the Google `<model-viewer>` web component. **No skeletal rigging is required** to display, rotate or zoom the model.

The model binary is not bundled in this repository change. On the user's Windows workstation, run these commands in the TopTigerAI project root:

```powershell
New-Item -ItemType Directory -Force static\models | Out-Null
Copy-Item videos\base.glb static\models\base.glb
```

Rebuild the API image using the same Compose overlay you normally use; for the RTX 4060 development deployment:

```powershell
docker compose -f docker-compose.yml -f deploy/gpu/docker-compose.gpu.yml -f deploy/gpu/docker-compose.rtx4050.yml up -d --build api
```

Open http://127.0.0.1:8000 and rotate the model by dragging. This viewer depends on access to the `model-viewer` JavaScript hosted at Google's CDN. A static GLB is an interactive display model **not** a video animation. The repository's existing GPU configuration is not otherwise affected.

If you want the model committed for sharing, ensure you have redistribution rights before running `git add static/models/base.glb` and pushing it.
