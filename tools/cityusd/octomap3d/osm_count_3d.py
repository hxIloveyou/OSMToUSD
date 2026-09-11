# -*- coding: utf-8 -*-
"""
osm_count.py —— 建筑统计（v2 自包含实现，仅依赖 osmium）
口径：building 标签（值不在排除集合）的 way/relation 计数 + relation 成员去重
"""
import osmium

_DEFAULT_EXCLUDE = ("no", "none", "false", "0")


class _Counter(osmium.SimpleHandler):
    def __init__(self, excluded):
        super().__init__()
        self._excluded = excluded
        self.way_count = 0
        self.relation_count = 0
        self.building_way_ids = set()      # 带 building 标签的 way id
        self.rel_outer_way_ids = set()     # building relation 的 outer 成员 way id
        self.rel_inner_way_ids = set()     # building relation 的 inner 成员 way id

    def _is_building(self, tag):
        return tag is not None and tag.strip().lower() not in self._excluded

    def way(self, w):
        if self._is_building(w.tags.get("building")):
            self.way_count += 1
            self.building_way_ids.add(w.id)

    def relation(self, r):
        if self._is_building(r.tags.get("building")):
            self.relation_count += 1
            for m in r.members:
                if m.type == "w":
                    if m.role == "outer":
                        self.rel_outer_way_ids.add(m.ref)
                    elif m.role == "inner":
                        self.rel_inner_way_ids.add(m.ref)


def count_buildings(osm_path, exclude=None):
    """统计建筑数量与去重。

    返回: {way_count, relation_count, total,
          overlap_outer, overlap_inner, dedup_total}
    """
    excluded = tuple(exclude) if exclude else _DEFAULT_EXCLUDE
    counter = _Counter(excluded)
    counter.apply_file(osm_path)
    overlap_outer = len(counter.building_way_ids & counter.rel_outer_way_ids)
    overlap_inner = len(counter.building_way_ids & counter.rel_inner_way_ids)
    total = counter.way_count + counter.relation_count
    return {
        "way_count": counter.way_count,
        "relation_count": counter.relation_count,
        "total": total,
        "overlap_outer": overlap_outer,
        "overlap_inner": overlap_inner,
        "dedup_total": total - overlap_outer - overlap_inner,
    }
