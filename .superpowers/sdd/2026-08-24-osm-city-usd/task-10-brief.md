### Task 10: USD layers, PointInstancer, package metadata

**Files:**
- Create: `tools/cityusd/usd_write.py`
- Create: `tools/cityusd/package.py`
- Test: `tests/test_usd_package.py`

**Interfaces:**
- Consumes: meshes, instance lists, `RasterMeta`, `FoundInputs`, `scene_id`
- Produces:

```python
def write_mesh(stage, path: str, points_cm, face_counts, face_indices, material_path: Optional[str]) -> None:
def write_point_instancer(stage, path: str, proto_prim_path: str, positions_cm, yaws_rad) -> None:
def write_placeholder_prototype(stage, path: str, verts, faces) -> None:
def write_environment_layer(path: Path) -> None:
def write_terrain_layer(path: Path, heightmap_rel: Optional[str], ortho_rel: Optional[str], meta: Optional[RasterMeta]) -> None:
def write_nav_layer(path: Path, pgm_rel: Optional[str], yaml_rel: Optional[str]) -> None:
def write_empty_overlay(path: Path, prim_name: str) -> None:
def write_world(path: Path, scene_id: str, sublayers: list[str]) -> None:
def write_meta(path: Path, payload: dict) -> None:
```

USD details:

- `UsdGeom.SetStageMetersPerUnit(stage, 0.01)` and `SetStageUpAxis(stage, UsdGeom.Tokens.z)`.
- Colors via `UsdShade.Material` UsdPreviewSurface; generate 8×8 PNG stripes for yellow/white markings under `textures/` if no library file.
- Buildings: for each LOD0 cell, prim `/World/City/Buildings/c{ix}_{iy}` with children `LOD0`, `LOD1`, `LOD2` meshes (LOD1/LOD2 may merge many footprints). Set customData `switch_distance_m` on parent.
- Terrain/nav layers: `UsdGeom.Xform` `/World/Terrain` and `/World/Nav` with `customData` keys `heightmap_png`, `ortho_png`, `map_pgm`, `map_yaml` as relative paths. Optional 1×1 hidden reference plane at Z=-1 cm, `visibility=invisible`.
- Overlays: `/World/Overlay/Equipment` etc. empty Xforms.
- World subLayers order exactly as spec §5.
- `meta.json` must include: `spec_version` `"1.0"`, `scene_id`, `crs`, `units.meters_per_unit` 0.01, layer paths, overlay paths, `lod` table, `vegetation_instancer` true, `lamp_instancer` true, `prototype_swap` true, `capabilities.has_building_lod` true.

- [ ] **Step 1: Write the failing test**

```python
from pxr import Usd, UsdGeom
from cityusd.package import write_world, write_empty_overlay
from cityusd.usd_write import write_environment_layer

def test_world_opens(tmp_path):
    env = tmp_path / "layers" / "environment.usda"
    env.parent.mkdir(parents=True)
    write_environment_layer(env)
    ov = tmp_path / "overlay"
    ov.mkdir()
    write_empty_overlay(ov / "equipment.usda", "Equipment")
    world = tmp_path / "World_test.usda"
    write_world(world, "test", [
        "./layers/environment.usda",
        "./overlay/equipment.usda",
    ])
    stage = Usd.Stage.Open(str(world))
    assert stage.GetDefaultPrim().GetName() == "World"
    assert UsdGeom.GetStageMetersPerUnit(stage) == 0.01
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_usd_package.py -v`

Expected: FAIL import

- [ ] **Step 3: Implement writers.** Copy prototype meshes into `models/prototypes/tree.usda` and `lamp.usda` referenced by PointInstancer `prototypes` relationship. Positions in centimeters.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_usd_package.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/cityusd/usd_write.py tools/cityusd/package.py tests/test_usd_package.py
git commit -m "feat: write World layers PointInstancer and meta.json"
```

---

