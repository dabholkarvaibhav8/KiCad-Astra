"""Explicit design constraints; these are user settings, not fabrication guarantees."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class LayoutRules:
    clearance_mm: float = 0.2
    track_width_mm: float = 0.25
    edge_clearance_mm: float = 0.3
    courtyard_clearance_mm: float = 0.1
    via_diameter_mm: float = 0.65
    via_drill_mm: float = 0.3
    annular_ring_mm: float = 0.15
    hole_clearance_mm: float = 0.25
    grid_mm: float = 0.25
    max_move_mm: float = 25.0
    via_cost_mm: float = 8.0
    max_search_nodes: int = 150_000
    route_timeout_s: float = 15.0
    max_connections: int = 32
    max_revisions: int = 2
    allow_vias: bool = False
    fixed_references: list[str] = field(default_factory=list)
    fixed_prefixes: list[str] = field(default_factory=lambda: ["J", "H", "MH"])
    manual_nets: list[str] = field(default_factory=list)
    allowed_layers: list[str] = field(default_factory=lambda: ["F.Cu", "B.Cu"])
    placement_regions: dict[str, list[list[float]]] = field(default_factory=dict)
    proximity: list[dict] = field(default_factory=list)

    def checked(self) -> "LayoutRules":
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name.endswith(("_mm", "_s")):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value <= 0
                ):
                    raise ValueError(f"{f.name} must be a positive finite number.")
        for name, limit in (
            ("max_search_nodes", 1_000_000),
            ("max_connections", 100),
            ("max_revisions", 5),
        ):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= limit:
                raise ValueError(f"{name} must be an integer from 0 to {limit}.")
        if self.max_search_nodes < 100 or self.grid_mm < 0.025:
            raise ValueError("Use at least 100 search nodes and a grid of at least 0.025 mm.")
        if self.via_diameter_mm < self.via_drill_mm + 2 * self.annular_ring_mm:
            raise ValueError("Via dimensions do not satisfy the requested annular ring.")
        for name in ("fixed_references", "fixed_prefixes", "manual_nets", "allowed_layers"):
            value = getattr(self, name)
            if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
                raise ValueError(f"{name} must be an array of nonempty strings.")
        if not self.allowed_layers or type(self.allow_vias) is not bool:
            raise ValueError("Choose routing layers and a boolean allow_vias value.")
        if not isinstance(self.placement_regions, dict) or not isinstance(self.proximity, list):
            raise ValueError("Invalid placement_regions or proximity constraints.")
        from shapely.geometry import Polygon

        for ref, points in self.placement_regions.items():
            if (
                not isinstance(ref, str)
                or not ref
                or not isinstance(points, list)
                or len(points) < 3
            ):
                raise ValueError(
                    "Placement regions require a reference and three or more 2D points."
                )
            if any(
                not isinstance(p, (list, tuple))
                or len(p) != 2
                or any(
                    isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                    for v in p
                )
                for p in points
            ):
                raise ValueError(f"Invalid finite 2D coordinates for placement region {ref}.")
            region = Polygon(points)
            if not region.is_valid or region.is_empty or region.area <= 0:
                raise ValueError(f"Invalid placement region for {ref}.")
        for rule in self.proximity:
            if (
                not isinstance(rule, dict)
                or set(rule) != {"a", "b", "max_mm"}
                or not isinstance(rule["a"], str)
                or not isinstance(rule["b"], str)
                or not rule["a"]
                or not rule["b"]
            ):
                raise ValueError(
                    "Proximity entries require a, b (pad labels such as U1.1), and max_mm."
                )
            if (
                isinstance(rule["max_mm"], bool)
                or not isinstance(rule["max_mm"], (int, float))
                or not math.isfinite(rule["max_mm"])
                or rule["max_mm"] <= 0
            ):
                raise ValueError("Proximity max_mm must be positive and finite.")
        return self

    def fixed(self, reference: str) -> bool:
        prefix = reference.rstrip("0123456789")
        return reference in self.fixed_references or prefix in self.fixed_prefixes

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LayoutRules":
        if not isinstance(data, dict):
            raise ValueError("Constraints must be a JSON object.")
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown constraints: {', '.join(sorted(unknown))}")
        return cls(**data).checked()

    @classmethod
    def load(cls, path: Path) -> "LayoutRules":
        from agent.tools import extract_json

        return cls.from_dict(extract_json(path.read_text(encoding="utf-8")))
