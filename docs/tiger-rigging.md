# Rigging the TopTiger prototype

The original `videos/base.glb` is an unrigged statue. The
`videos/base_rigged_prototype.glb` generated from it contains an experimental
18-joint skeleton and automatic heuristic vertex weights. The character was
**not manually skinned or visually deformation-tested**, and the result
should not be described as production-ready animation.

To reproduce from the original file in the repository root:

```powershell
python -m pip install numpy
python tools/rig_toptiger.py --input videos/base.glb --output videos/base_rigged_prototype.glb
```

The script assumes a **specific** single-mesh, single-primitive, Y-up export
of the tiger statue; it is not a general-purpose auto-rigger.

To commit an exported GLB from your own machine:

```powershell
git add videos/base_rigged_prototype.glb
git commit -m "Add prototype rigged TopTiger boxer model"
git push origin main
```

GitHub's regular file limit is 100 MB. Avoid committing private/licensed
assets unless you have permission to distribute them. Preserve the
unrigged original for comparison.
