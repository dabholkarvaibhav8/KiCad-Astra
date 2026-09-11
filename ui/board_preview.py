"""Interactive physical preview: layer filter, proposed overlays, pan, zoom and selection."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from kicad.geometry import decode
from kicad.validation import copper_items, projected_scene

CANVAS = "#090D18"
COLORS = {"F.Cu": "#FF6B78", "B.Cu": "#5E8BFF"}


class BoardPreview(ttk.Frame):
    def __init__(self, parent, on_select=None):
        super().__init__(parent)
        self.on_select = on_select
        self.state = None
        self.bundle = None
        self.selected = None
        self.scale = 10
        self.offset = [20, 20]
        self.fitted = False
        self.drag = None
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(4, 8))
        self.layer = tk.StringVar(value="All layers")
        self.layers = ttk.Combobox(
            top, textvariable=self.layer, values=["All layers"], state="readonly", width=16
        )
        self.layers.pack(side="left")
        self.layers.bind("<<ComboboxSelected>>", lambda e: self.draw())
        self.overlay = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Show proposal", variable=self.overlay, command=self.draw).pack(
            side="left", padx=12
        )
        ttk.Button(top, text="Fit board", command=self.fit).pack(side="right")
        ttk.Label(top, text="Wheel: zoom · drag: pan", style="Muted.TLabel").pack(
            side="right", padx=12
        )
        self.canvas = tk.Canvas(self, bg=CANVAS, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.fit() if not self.fitted else None)
        self.canvas.bind("<MouseWheel>", self.zoom)
        self.canvas.bind("<Button-4>", lambda e: self.zoom(e, 1))
        self.canvas.bind("<Button-5>", lambda e: self.zoom(e, -1))
        self.canvas.bind("<ButtonPress-1>", lambda e: setattr(self, "drag", (e.x, e.y)))
        self.canvas.bind("<B1-Motion>", self.pan)
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))
        self.note = ttk.Label(
            self, text="Capture a board to see its geometry.", style="Muted.TLabel"
        )
        self.note.pack(fill="x", pady=6)

    def set_scene(self, state, bundle=None):
        self.state = state
        self.bundle = bundle
        self.layers.configure(values=["All layers", *state["copper_layers"]])
        self.fit()

    def fit(self):
        if not self.state or not self.state.get("outline"):
            return
        x0, y0, x1, y1 = decode(self.state["outline"]).bounds
        w = max(200, self.canvas.winfo_width())
        h = max(200, self.canvas.winfo_height())
        self.scale = min((w - 70) / max(x1 - x0, 1), (h - 70) / max(y1 - y0, 1))
        self.offset = [
            (w - (x1 - x0) * self.scale) / 2 - x0 * self.scale,
            (h - (y1 - y0) * self.scale) / 2 - y0 * self.scale,
        ]
        self.fitted = self.canvas.winfo_width() > 100
        self.draw()

    def coords(self, points):
        return [
            value
            for x, y in points
            for value in (x * self.scale + self.offset[0], y * self.scale + self.offset[1])
        ]

    def geometry(self, geometry, *, fill="", outline="", width=1, tags=(), dash=None):
        g = decode(geometry) if isinstance(geometry, dict) else geometry
        if g.is_empty:
            return
        if g.geom_type in {"MultiPolygon", "GeometryCollection"}:
            for part in g.geoms:
                self.geometry(part, fill=fill, outline=outline, width=width, tags=tags, dash=dash)
        elif g.geom_type == "Polygon":
            kwargs = {"fill": fill, "outline": outline, "width": width, "tags": tags}
            if dash:
                kwargs["dash"] = dash
            self.canvas.create_polygon(self.coords(g.exterior.coords), **kwargs)
            for hole in g.interiors:
                self.canvas.create_polygon(
                    self.coords(hole.coords),
                    fill=CANVAS if fill else "",
                    outline=outline,
                    width=width,
                    tags=tags,
                )

    def draw(self):
        self.canvas.delete("all")
        if not self.state:
            return
        state = self.state
        active = self.layer.get()
        proposed = self.overlay.get() and self.bundle is not None
        if state.get("outline"):
            self.geometry(state["outline"], fill="#12243B", outline="#64D2FF", width=2)
        scene = state
        if proposed:
            try:
                scene = projected_scene(state, self.bundle.proposal["placements"])
            except (KeyError, ValueError):
                scene = state
        for item in scene["copper"]:
            if active != "All layers" and item["layer"] != active:
                continue
            color = (
                "#D7B56D"
                if item["kind"] == "pad"
                else "#18344C"
                if item["kind"] == "zone"
                else "#55758A"
            )
            self.geometry(item["geometry"], fill=color)
        for area in scene["keepouts"]:
            if active == "All layers" or not area["layers"] or active in area["layers"]:
                self.geometry(area["geometry"], outline="#FF9F0A", dash=(3, 3))
        changed = (
            {p["reference"] for p in self.bundle.proposal["placements"]} if proposed else set()
        )
        for fp in state["footprints"]:
            if fp["reference"] in changed:
                for g in fp["courtyards"].values():
                    self.geometry(g, outline="#7D8597", dash=(4, 4))
        for fp in scene["footprints"]:
            ref = fp["reference"]
            tag = "ref:" + ref
            color = "#64D2FF" if ref in changed else "#A7B0C0"
            if ref == self.selected:
                color = "#FFD60A"
            for side, g in fp["courtyards"].items():
                if active == "All layers" or active == ("F.Cu" if side == "front" else "B.Cu"):
                    self.geometry(g, outline=color, width=2 if ref in changed else 1, tags=(tag,))
            px, py = self.coords([fp["position_mm"]])
            self.canvas.create_text(
                px,
                py - 9,
                text=ref + (" •" if fp["locked"] else ""),
                fill=color,
                font=("Segoe UI", 9, "bold"),
                tags=(tag,),
            )
            self.canvas.tag_bind(tag, "<Button-1>", lambda e, r=ref: self.select(r))
        if proposed:
            for route in self.bundle.routes:
                for item in copper_items(route):
                    if active == "All layers" or item["layer"] == active:
                        self.geometry(item["geometry"], fill=COLORS.get(item["layer"], "#BF5AF2"))
        if proposed:
            for op in self.bundle.label_ops:
                if active == "All layers" or active == (
                    "F.Cu" if op["side"] == "front" else "B.Cu"
                ):
                    self.geometry(op["geometry"], outline="#F5F7FF", width=1)
                    self.canvas.create_text(
                        *self.coords([(op["x_mm"], op["y_mm"])]),
                        text=op["reference"],
                        fill="#F5F7FF",
                        font=("Segoe UI", 10, "bold"),
                        tags=("label-proposal",),
                    )
        for hole in scene["holes"]:
            self.geometry(hole["geometry"], fill=CANVAS, outline="#697386")
        self.note.configure(
            text="Cyan: proposed placement · red/blue: proposed copper · dashed: original placement · zones are conservative obstacles"
        )

    def select(self, ref):
        self.selected = ref
        self.draw()
        if self.on_select:
            self.on_select(ref)

    def zoom(self, event, direction=None):
        direction = direction if direction is not None else (1 if event.delta > 0 else -1)
        factor = 1.15**direction
        if not 0.1 < self.scale * factor < 3000:
            return
        self.offset = [
            event.x - (event.x - self.offset[0]) * factor,
            event.y - (event.y - self.offset[1]) * factor,
        ]
        self.scale *= factor
        self.fitted = True
        self.draw()

    def pan(self, event):
        if self.drag:
            self.offset[0] += event.x - self.drag[0]
            self.offset[1] += event.y - self.drag[1]
            self.drag = (event.x, event.y)
            self.draw()
