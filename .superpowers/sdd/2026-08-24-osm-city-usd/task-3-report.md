# Task 3 Review: OSM parser

## Verdict

**Conditional pass.** The XML path meets the brief and the fixture test passes (per prior GREEN run). Shared types, CRS wiring, and tag filtering are solid. The PBF handler is present but untested and likely fragile on way-node resolution; test coverage stops at one happy-path XML assertion.

---

## Spec compliance

| Requirement | Status | Evidence |
|---|---|---|
| `parse_osm(path, origin=None) -> OsmData` | ✅ | `osm_parse.py:35-42` |
| `OsmWay` / `OsmNode` / `OsmData` dataclasses match brief | ✅ | `osm_parse.py:12-32` |
| `.osm` via `xml.etree.ElementTree` | ✅ | `osm_parse.py:90-125` |
| `.osm.pbf` via `osmium.SimpleHandler` | ✅ | `osm_parse.py:128-169` |
| `origin is None` → bbox center | ✅ | `osm_parse.py:53-54`, `45-55` |
| Skip ways with fewer than 2 nodes | ✅ | `osm_parse.py:64-65` |
| Convert lon/lat with `lonlat_to_local` | ✅ | `osm_parse.py:68`, `85` |
| Return only tagged ways/nodes | ✅ | `osm_parse.py:66-67`, `83-84` |
| `lonlat_bbox` as west,south,east,north | ✅ | `osm_parse.py:50-52`, `124` |
| Fixture: 1 building, 1 named residential, 1 tree | ✅ | `tests/fixtures/tiny.osm:187-203` |
| `origin.epsg == 32650` (lon 119 → zone 50) | ✅ | `tests/test_osm_parse.py:16` |
| Closed building ring detected | ✅ | `tests/test_osm_parse.py:13`; `osm_parse.py:69-72` |
| Unicode road name preserved | ✅ | `tests/test_osm_parse.py:14`; fixture `tests/fixtures/tiny.osm:195` |
| PBF path correctness under non-canonical file order | ⚠️ | `osm_parse.py:151-154` — see issues |
| Edge cases (empty file, explicit `origin`, bbox values) | ⚠️ | Not specified in brief; not tested |

---

## Strengths

1. **Clean shared pipeline.** XML and PBF both funnel through `_bbox_and_origin`, `_build_ways`, and `_build_nodes` (`osm_parse.py:45-87`, `119-125`, `163-168`), avoiding duplicated projection/tag logic.

2. **Spec-accurate data model.** Field names, types, and docstrings match the brief exactly (`osm_parse.py:12-32`).

3. **Tag-only output.** Untagged geometry is excluded from results, matching “classify later” intent (`osm_parse.py:66-67`, `83-84`). Untagged nodes still contribute to bbox/origin via the XML scan (`osm_parse.py:102-103`).

4. **Robust closed-ring detection.** Checks projected coords first, then falls back to lon/lat identity (`osm_parse.py:69-72`) — sensible for rings that repeat the first node in OSM.

5. **Fixture fidelity.** `tests/fixtures/tiny.osm` matches the brief byte-for-byte in structure; the test encodes the three feature classes plus EPSG check (`tests/test_osm_parse.py:8-16`).

6. **Lazy `osmium` import.** Keeps XML-only callers free of the native dependency until PBF is requested (`osm_parse.py:129`).

---

## Issues

### 1. PBF way coords ignore `nd.location` (medium)

`osm_parse.py:151-154` resolves way vertices only via `node_lonlat.get(nd.ref)`, even though `apply_file(..., locations=True)` (`osm_parse.py:157`) embeds coordinates on way node refs. If a way is visited before its nodes land in the dict (non-standard PBF order, or partial reads), coords are silently dropped and the way may be skipped as `<2` nodes.

**Fix direction:** prefer `nd.location` when valid; fall back to `node_lonlat`.

### 2. Misleading PBF comment (low)

`osm_parse.py:159` says “Prefer locations from way nodes if file order put ways first” but no such logic exists — the comment describes unimplemented behavior.

### 3. Empty XML file unguarded (low)

`_bbox_and_origin` calls `min(lons)` / `max(lats)` with no empty-list guard (`osm_parse.py:50-51`). PBF path raises `ValueError` (`osm_parse.py:160-161`); XML path would crash with `ValueError` on an empty `<osm>` — inconsistent and outside brief scope, but worth noting.

### 4. Closed detection uses exact float equality on projected coords (low)

`osm_parse.py:69` compares `coords_m[0] == coords_m[-1]`. Rounding in `lonlat_to_local` could theoretically fail before the lon/lat fallback at `osm_parse.py:71-72`. Unlikely for the fixture; tolerances may be needed later.

### 5. Thin test surface (medium)

`tests/test_osm_parse.py` has a single test with no coverage for:

- PBF parsing (half the stated interface)
- Explicit `origin=` argument
- `lonlat_bbox` values
- `coords_m` / `xy_m` local-meter correctness
- `<2`-node way skip behavior
- Untagged-way exclusion (water way id 30 is tagged and returned but unasserted)

Prior run: `test_parse_tiny_counts PASSED` (1 passed). GREEN is real for XML; PBF remains unverified.

---

## Task quality

**Brief:** Clear interfaces, fixture coordinates, TDD steps, and dependency boundaries (`Origin`, `lonlat_to_local`). The “tags only” rule and skip-`<2`-nodes rule are explicit. Good incremental task.

**Implementation:** Meets the written contract for the tested XML path with readable structure. The main gap is shipping a PBF handler without a fixture or test to prove parity with XML.

**Recommendation:** Accept for Task 3 milestone if downstream tasks consume XML first. Before relying on `.osm.pbf` in production, add a tiny PBF fixture (or round-trip test) and fix way-node location resolution at `osm_parse.py:151-154`.

---

## Test evidence (not re-run)

Per prior task report:

- RED: `ModuleNotFoundError: No module named 'cityusd.osm_parse'`
- GREEN: `tests/test_osm_parse.py::test_parse_tiny_counts PASSED` (1 passed in 0.10s)

---

## Fix report (review findings)

**Status:** DONE  
**Commits:** none

### Fixes

1. **PBF way coords:** prefer `nd.location` when `nd.location.valid()`, else fall back to `node_lonlat.get(nd.ref)`. Removed misleading comment; empty-file guard centralized in `_bbox_and_origin`.
2. **PBF test:** `test_parse_tiny_pbf_counts` writes a tiny `.osm.pbf` via `osmium.SimpleWriter` / `osmium.osm.mutable` matching `tiny.osm` features, then asserts same counts (1 building, 1 named residential, 1 tree) + EPSG 32650.
3. **Empty file:** `_bbox_and_origin` raises `ValueError("OSM file contains no nodes")` when `lons`/`lats` empty; covered by `test_parse_empty_osm_raises`.

### Covering tests

- `test_parse_tiny_counts` (XML)
- `test_parse_tiny_pbf_counts` (PBF)
- `test_parse_empty_osm_raises` (empty XML)

### Command

```
$env:PYTHONPATH="E:\UEWork\ROS2Test\CityUsd\tools"; pytest tests/test_osm_parse.py -v
```

### Output

```
tests/test_osm_parse.py::test_parse_tiny_counts PASSED
tests/test_osm_parse.py::test_parse_tiny_pbf_counts PASSED
tests/test_osm_parse.py::test_parse_empty_osm_raises PASSED
3 passed in 0.20s
```
