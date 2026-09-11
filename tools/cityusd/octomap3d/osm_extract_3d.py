# -*- coding: utf-8 -*-
"""
osm_extract.py —— OSM 建筑提取（v2 自包含实现，仅依赖 osmium）

返回结构（供 pipeline 使用）：
  buildings: list[dict]
    way 型:      {'id','tags','source':'way', 'ring': [(lon,lat),...]}
    relation 型: {'id','tags','source':'relation','outer':[[(lon,lat),...],...],
                  'inner':[[(lon,lat),...],...]}
  stats: dict  统计（way_count/relation_count/overlap/dedup 及各类跳过）
"""
from collections import Counter

import osmium

_DEFAULT_EXCLUDE = ("no", "none", "false", "0")


class _RelationPass(osmium.SimpleHandler):
    """第 1 遍：只收集带 building 标签的 relation（成员 way id 与角色）"""

    def __init__(self, excluded):
        super().__init__()
        self._excluded = excluded
        self.rels = []
        self.stats = Counter()

    def relation(self, r):
        tag = r.tags.get("building")
        if tag is None or tag.strip().lower() in self._excluded:
            return
        outer = [m.ref for m in r.members if m.type == "w" and m.role == "outer"]
        inner = [m.ref for m in r.members if m.type == "w" and m.role == "inner"]
        self.rels.append({"id": r.id, "tags": dict(r.tags), "outer": outer, "inner": inner})
        self.stats["relation_count"] += 1


class _WayPass(osmium.SimpleHandler):
    """第 2 遍：收集 building way 与 relation 成员 way（locations=True 带坐标）"""

    def __init__(self, member_wids, excluded):
        super().__init__()
        self._member_wids = member_wids
        self._excluded = excluded
        self.ways = {}               # wid -> (tags, [(lon,lat),...])
        self.building_way_ids = set()
        self.stats = Counter()

    def way(self, w):
        tags = dict(w.tags)
        tag = tags.get("building")
        is_building = tag is not None and tag.strip().lower() not in self._excluded
        if is_building:
            self.stats["way_count"] += 1
            self.building_way_ids.add(w.id)
        if not (is_building or w.id in self._member_wids):
            return
        ring = []
        for n in w.nodes:
            try:
                loc = n.location
            except Exception:
                loc = None
            if loc is not None:
                ring.append((loc.lon, loc.lat))
            else:
                self.stats["missing_node_refs"] += 1
        self.ways[w.id] = (tags, ring)
        self.stats["ways_kept"] += 1


def extract_buildings(path, exclude=None):
    """提取建筑物。返回 (buildings, stats)"""
    excluded = tuple(exclude) if exclude else _DEFAULT_EXCLUDE
    stats = Counter()

    # ---- 第 1 遍：relation ----
    rel_pass = _RelationPass(excluded)
    rel_pass.apply_file(path)
    rels = rel_pass.rels
    stats.update(rel_pass.stats)

    outer_wids, inner_wids = set(), set()
    for rel in rels:
        outer_wids.update(rel["outer"])
        inner_wids.update(rel["inner"])
    member_wids = outer_wids | inner_wids

    # ---- 第 2 遍：way（带节点坐标）----
    way_pass = _WayPass(member_wids, excluded)
    way_pass.apply_file(path, locations=True)
    stats.update(way_pass.stats)
    ways = way_pass.ways

    # ---- 去重统计 ----
    way_count = stats["way_count"]
    relation_count = stats["relation_count"]
    overlap_outer = len(way_pass.building_way_ids & outer_wids)
    overlap_inner = len(way_pass.building_way_ids & inner_wids)
    stats["overlap_outer"] = overlap_outer
    stats["overlap_inner"] = overlap_inner
    stats["dedup_total"] = way_count + relation_count - overlap_outer - overlap_inner

    # ---- 组装建筑物 ----
    buildings = []
    skip_member = 0
    for wid, (tags, ring) in ways.items():
        if wid in member_wids:
            if "building" in tags:
                skip_member += 1   # 已在 relation 中处理（去重）
            continue
        if "building" not in tags:
            continue
        if len(ring) < 4:
            stats["skip_too_few_nodes"] += 1
            continue
        buildings.append({"id": wid, "tags": tags, "ring": ring, "source": "way"})
    stats["skip_relation_member"] = skip_member

    for rel in rels:
        # 坏掉的 outer 环（点数不足 3）只跳过该环本身；无有效外环才丢弃整个 relation
        outer = []
        for wid in rel["outer"]:
            ring = ways.get(wid, (None, []))[1]
            if len(ring) >= 3:
                outer.append(ring)
        if not outer:
            stats["skip_rel_incomplete"] += 1
            continue
        inner = []
        for wid in rel["inner"]:
            ring = ways.get(wid, (None, []))[1]
            if len(ring) >= 3:
                inner.append(ring)
        buildings.append({"id": rel["id"], "tags": rel["tags"],
                          "outer": outer, "inner": inner, "source": "relation"})

    stats["buildings_total"] = len(buildings)
    return buildings, dict(stats)
