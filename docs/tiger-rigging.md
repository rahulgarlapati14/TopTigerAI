# Rigging the TopTiger prototype

The original `videos/base.glb` is an unrigged statue. The
`videos/base_rigged_prototype.glb` generated from it contains an experimental
18-joint skeleton and automatic heuristic vertex weights. The character was
**not manually skinned or visually deformation-tested**, and the result
should not be described as production-ready animation.

The prototype rigged GLB was generated from the original mesh with an experimental one-off rigging script. The GLB binary must be copied into `videos/base_rigged_prototype.glb` from the operator's machine before it can be used by the app. The rigging process assumes this exact single-mesh, single-primitive Y-up tiger export and is not a general-purpose auto-rigger.

To commit an exported GLB from your own machine:

```powershell
git add videos/base_rigged_prototype.glb
git commit -m "Add prototype rigged TopTiger boxer model"
git push origin main
```

GitHub's regular file limit is 100 MB. Avoid committing private/licensed
assets unless you have permission to distribute them. Preserve the
unrigged original for comparison.
