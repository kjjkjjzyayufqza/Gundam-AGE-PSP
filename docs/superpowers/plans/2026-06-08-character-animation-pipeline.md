# Character Animation Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-command character extraction path that exports textures, materials, a static OBJ, and can explicitly run experimental compatible XMTN pose export.

**Architecture:** Extend the existing pipeline instead of creating a second archive/model stack. `age_asset_pipeline.py` will discover sibling archives and invoke the existing StudioElevenLib wrapper; `age_pose_export.py` will expose reusable pose selection/export functions. Compatibility is proven with shared XMPR/XMTN node hashes, not inferred from filenames alone.

**Tech Stack:** Python 3.11 standard library, existing Gundam AGE tools, .NET 9, Tiniifan/StudioElevenLib, `unittest`.

---

### Task 1: Pose Selection and Reusable Export API

**Files:**
- Modify: `tools/age_pose_export.py`
- Modify: `tools/tests/test_age_pose_export.py`

- [x] **Step 1: Add failing tests for representative-frame scoring**

Create synthetic `BoneScale` tracks where frame 0 hides nodes with scale
`0.0001` and frame 10 exposes them with scale `1.0`. Assert that
`select_representative_frame(data, relevant_nodes)` returns frame 10.

- [x] **Step 2: Run the focused tests**

Run:

```powershell
python -m unittest tools.tests.test_age_pose_export -v
```

Expected: the new frame-selection test fails before implementation.

- [x] **Step 3: Implement frame selection**

Add:

```python
def animation_node_names(data: dict) -> set[str]: ...
def select_representative_frame(data: dict, relevant_nodes: set[str]) -> int: ...
```

Score every integer frame from `0` through `FrameCount`. First maximize the
number of relevant nodes whose three scale components exceed `0.01`; then
minimize logarithmic distance from unit scale; then prefer the earliest frame.

- [x] **Step 4: Extract the command body into a callable API**

Add:

```python
def export_posed_obj(
    root: Path,
    animation_json: Path,
    frame: float,
    out_path: Path,
    manifest_path: Path | None,
    triangulation: str,
    keep_degenerate_faces: bool,
    mtllib: str | None,
    rotation_mode: str = "studioeleven",
) -> dict: ...
```

Keep `command_export` as a thin CLI adapter.

- [x] **Step 5: Add a rotation convention diagnostic**

Accept `rotation_mode` values `studioeleven` and `inverse`. The default keeps
the raw StudioElevenLib XMTN quaternion; `inverse` conjugates xyz for comparison
with Metanoia's convention. Record the selected mode in every pose manifest.

- [x] **Step 6: Run tests and syntax checks**

Run:

```powershell
python -m unittest discover -s tools\tests -v
python -m py_compile tools\age_pose_export.py
```

Expected: all tests pass and compilation exits zero.

### Task 2: Animation Archive Discovery and Compatibility

**Files:**
- Modify: `tools/age_asset_pipeline.py`
- Create: `tools/tests/test_age_character_pipeline.py`

- [x] **Step 1: Add failing discovery tests**

Use temporary files named `fn024000_p000.xc`, `fn024000_s240.xc`,
`fn024000_v360.xc`, and `other_s240.xc`. Assert that only the two
`fn024000` sibling animations are returned.

- [x] **Step 2: Implement sibling discovery**

Add:

```python
def model_archive_prefix(path: Path) -> str: ...
def discover_animation_archives(model_archive: Path) -> list[Path]: ...
```

Require the model stem to end in `_p<digits>` and animation stems to match the
same prefix plus `_(s|v)<digits>`.

- [x] **Step 3: Implement hash compatibility**

Add:

```python
def model_node_hashes(model_manifest: dict) -> set[str]: ...
def animation_node_hashes(animation_data: dict) -> set[str]: ...
def compatibility_record(model_nodes: set[str], animation_nodes: set[str]) -> dict: ...
```

Record overlap count, model coverage, animation coverage, and sorted hashes.
Never export a pose when overlap count is zero.

- [x] **Step 4: Run discovery tests**

Run:

```powershell
python -m unittest tools.tests.test_age_character_pipeline -v
```

Expected: discovery and compatibility tests pass.

### Task 3: One-Command Character Pipeline

**Files:**
- Modify: `tools/age_asset_pipeline.py`
- Modify: `tools/tests/test_age_character_pipeline.py`

- [x] **Step 1: Add the `from-character` command**

The command reuses all `from-xpck` arguments and adds:

```text
--animation-policy best|all|none
--animation-archive PATH
--pose-frame auto|NUMBER
--rotation-mode studioeleven|inverse
--rebuild-animation-probe
```

Default to static-only `none`, `auto`, and `studioeleven`. Explicit
`--animation-policy best|all` enables the experimental pose path.

- [x] **Step 2: Build or locate the StudioElevenLib probe**

If `tools/StudioElevenAnimationProbe/bin/Release/net9.0/StudioElevenAnimationProbe.dll`
does not exist, run:

```powershell
dotnet build tools\StudioElevenAnimationProbe\StudioElevenAnimationProbe.csproj -c Release
```

Capture the command, exit code, stdout, and stderr in the pipeline manifest.

- [x] **Step 3: Extract and parse candidate animation archives**

Extract each candidate under:

```text
<out-dir>/animations/<archive-stem>/extracted/
```

Parse each `.mtn2` into:

```text
<out-dir>/animations/<archive-stem>/<mtn-stem>.animation.json
```

- [x] **Step 4: Rank and export compatible poses**

Rank by model-node coverage, overlap count, and archive name. For `best`,
export only the top candidate; for `all`, export every compatible candidate.
Use the automatic representative frame unless the user supplied a number.

- [x] **Step 5: Record a complete animation manifest**

Add `animations` to `_asset_pipeline_manifest.json`, including discovered
archives, extraction failures, parser results, compatibility scores, selected
frame, pose OBJ, pose JSON, and rotation mode.

- [x] **Step 6: Run all tests**

Run:

```powershell
python -m unittest discover -s tools\tests -v
python -m py_compile tools\age_asset_pipeline.py tools\age_pose_export.py
```

Expected: all tests pass.

### Task 4: Multi-Character Validation

**Files:**
- Generated outputs only under: `outputs/pipeline/`
- Modify: `docs/RESEARCH_LOG.md`

- [x] **Step 1: Run `fn024000` end to end**

Run:

```powershell
python tools\age_asset_pipeline.py from-character "<PSP_RESOURCE_ROOT>\chr\fn024000\fn024000_p000.xc" --out-dir outputs\pipeline\fn024000_character_auto --name fn024000_p000 --triangulation strip --overwrite --animation-policy best
```

Expected: textures, MTL, static OBJ, parsed XMTN JSON, and one posed OBJ.

- [x] **Step 2: Run two independent character samples**

Run the same command for `fn001000_p000.xc` and `fn001001_p000.xc`.
Expected: no parser failures, nonzero model/XMTN hash overlap, and every
animation-dependent vertex transformed.

- [x] **Step 3: Audit output references**

Verify every emitted OBJ `mtllib` exists and every emitted MTL `map_Kd`
resolves to an existing PNG.

- [x] **Step 4: Audit posed geometry**

Verify all OBJ vertex coordinates are finite, every face index is within the
vertex count, bounds are nonzero, and automatic pose bounds remain below
`10000` units on every axis.

### Task 5: Documentation and Research Log

**Files:**
- Modify: `README.md`
- Modify: `docs/ASSET_EXTRACTION_RESEARCH.md`
- Modify: `docs/RESEARCH_LOG.md`

- [x] **Step 1: Document the exact one-command workflow**

Add the `from-character` command, output layout, selection policy, and
manifest fields.

- [x] **Step 2: Record GitHub tool usage**

Document that StudioElevenLib parses XMTN, Metanoia confirms slot 7/8 semantics
and provides an alternate quaternion convention, and openTri supplies PSP
deswizzle evidence.

- [x] **Step 3: Record dated evidence**

Append the commands, sample names, hash-overlap metrics, selected frames,
bounds, test results, and remaining uncertainty to `docs/RESEARCH_LOG.md`
under `2026-06-08`.

- [x] **Step 4: Run a documentation consistency scan**

Run:

```powershell
rg -n "from-character|StudioElevenLib|Metanoia|rotation_mode|2026-06-08" README.md docs
```

Expected: commands and tool attributions are present in both operational and
research documentation.




