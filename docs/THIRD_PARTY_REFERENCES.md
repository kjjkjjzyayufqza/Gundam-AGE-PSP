# Third-Party References

Date: 2026-06-09

Third-party repositories are not tracked in this repo. Local clones may exist
under ignored `external_tools/`, but committed documentation should use upstream
links.

## Directly Used

| Repo | Use |
|---|---|
| [Tiniifan/StudioElevenLib](https://github.com/Tiniifan/StudioElevenLib) | Local optional animation probe wraps `AnimationManager`; source also informed XPVB/XPVI/XMPR and image comparisons |
| [albe/openTri](https://github.com/albe/openTri) | PSP swizzle/unswizzle reference; directly informed IMGP black-speckle fix |

## Important References

| Repo | Use |
|---|---|
| [Tiniifan/studio_eleven](https://github.com/Tiniifan/studio_eleven) | Blender importer behavior for PRM vertex handling, MBN armature behavior, and animation channel conversion |
| [Ploaj/Metanoia](https://github.com/Ploaj/Metanoia) | Historical Level-5 XI/PRM/animation code; confirms slot 7 weights and slot 8 bone indices |
| [FanTranslatorsInternational/Kuriimu2](https://github.com/FanTranslatorsInternational/Kuriimu2) | Level-5 compression and XPCK reference |
| [IcySon55/Kuriimu](https://github.com/IcySon55/Kuriimu) | Older XPCK support reference |

## Checked But Not Adopted

| Repo | Result |
|---|---|
| [Tiniifan/Pingouin](https://github.com/Tiniifan/Pingouin) | GUI archive manager supports XPCK; no useful CLI path for current workflow |
| [Tiniifan/Level5ResourceEditor](https://github.com/Tiniifan/Level5ResourceEditor) | Targets 3DS-style `RES.bin`/`XRES`; AGE PSP `CHRP00` differs |
| [Tiniifan/level5_material](https://github.com/Tiniifan/level5_material) | Tested on AGE `.mtr`; failed with invalid header because AGE PSP `MTRP00` is different |
| [SIEBEN5106/Gundam-AGE-PSP-Texture-Pack](https://github.com/SIEBEN5106/Gundam-AGE-PSP-Texture-Pack) | Reference corpus for replacement textures, not an extractor |

## Local Upload Boundary

Do not upload:

- `external_tools/`;
- `tools/StudioElevenAnimationProbe/`;
- third-party build outputs;
- copied upstream source trees.

Use links in this document instead.



