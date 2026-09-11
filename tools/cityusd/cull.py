"""Distance cull metadata for UE (Max Draw Distance / HISM cull).

Values are authored in meters; cm companions match UE units (metersPerUnit=0.01).
Import/post-process should apply these to StaticMeshComponent / HISM — USD alone
does not auto-cull in Unreal.
"""
# 中文说明：UE 距离剔除元数据（Max Draw Distance / HISM）。

from __future__ import annotations

# End distance: fully culled beyond this (building MaxDrawDistance).
# Instancers: fade between start and end (HISM InstanceStart/EndCullDistance).
CULL_BUILDING_M = 1200.0
CULL_LAMP_START_M = 250.0
CULL_LAMP_END_M = 400.0
CULL_SIGN_START_M = 300.0
CULL_SIGN_END_M = 500.0
CULL_ARROW_START_M = 80.0
CULL_ARROW_END_M = 150.0
CULL_TREE_START_M = 400.0
CULL_TREE_END_M = 800.0


def m_to_cm(distance_m: float) -> float:
    return float(distance_m) * 100.0


def mesh_cull_custom_data(end_m: float) -> dict:
    end_m = float(end_m)
    return {
        "cull_mode": "max_draw_distance",
        "cull_distance_m": end_m,
        "cull_distance_cm": m_to_cm(end_m),
        "unreal_max_draw_distance_cm": m_to_cm(end_m),
    }


def instancer_cull_custom_data(start_m: float, end_m: float) -> dict:
    start_m = float(start_m)
    end_m = float(end_m)
    if end_m < start_m:
        end_m = start_m
    return {
        "cull_mode": "hism_instance_cull",
        "cull_start_m": start_m,
        "cull_end_m": end_m,
        "cull_start_cm": m_to_cm(start_m),
        "cull_end_cm": m_to_cm(end_m),
        "unreal_instance_start_cull_distance_cm": m_to_cm(start_m),
        "unreal_instance_end_cull_distance_cm": m_to_cm(end_m),
    }


def cull_policy_summary() -> dict:
    return {
        "building_m": CULL_BUILDING_M,
        "lamp_m": [CULL_LAMP_START_M, CULL_LAMP_END_M],
        "sign_m": [CULL_SIGN_START_M, CULL_SIGN_END_M],
        "arrow_m": [CULL_ARROW_START_M, CULL_ARROW_END_M],
        "tree_m": [CULL_TREE_START_M, CULL_TREE_END_M],
        "note": "Apply customData * _cm fields to UE components after USD import.",
    }
