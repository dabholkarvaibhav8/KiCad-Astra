"""Desktop planning workbench. Worker threads communicate only through a queue."""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from agent.astra_client import DEFAULT_MODEL, PlannerClient
from agent.tools import extract_json
from agent.workflow import evaluate, generate
from kicad.board_reader import digest
from kicad.config import LayoutRules
from kicad.labels import LabelStyle, arrange_labels
from kicad.quality import inspect_quality
from kicad.transactions import apply_checked, preview_drc
from support import VERSION
from ui.board_preview import BoardPreview

MODES = {"Review": "review", "Placement": "placement", "Routing": "routing"}
FONT = "SF Pro Display" if sys.platform == "darwin" else "Segoe UI"
MONO = "SF Mono" if sys.platform == "darwin" else "Consolas"
BG = "#F5F5F7"
SURFACE = "#FFFFFF"
INK = "#1D1D1F"
MUTED = "#6E6E73"
LINE = "#D9D9DE"
BLUE = "#007AFF"


class AssistantPanel:
    def __init__(self, root, session):
        self.root, self.session = root, session
        self.snapshot = None
        self.bundle = None
        self.receipt = None
        self.busy = False
        self.closing = False
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.model = tk.StringVar(value=DEFAULT_MODEL)
        self.key = tk.StringVar()
        self.effort = tk.StringVar(value="high")
        self.mode = tk.StringVar(value="Placement")
        self.consent = tk.BooleanVar()
        self.status = tk.StringVar(value="Capture a saved KiCad board to start.")
        root.title(f"KiCad Astra {VERSION} — PCB Layout Workbench")
        root.geometry("1380x900")
        root.minsize(1080, 760)
        root.configure(background=BG)
        root.option_add("*tearOff", False)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self.root.after(100, self._poll)
        self._capture()

    def _build(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=INK, font=(FONT, 10))
        style.configure("TFrame", background=BG)
        style.configure("Surface.TFrame", background=SURFACE)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("Surface.TLabel", background=SURFACE, foreground=INK)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("SurfaceMuted.TLabel", background=SURFACE, foreground=MUTED)
        style.configure("Title.TLabel", background=SURFACE, foreground=INK, font=(FONT, 24, "bold"))
        style.configure(
            "Eyebrow.TLabel",
            background=SURFACE,
            foreground=BLUE,
            font=(FONT, 9, "bold"),
        )
        style.configure(
            "TButton",
            background=SURFACE,
            foreground=INK,
            bordercolor=LINE,
            focusthickness=0,
            padding=(12, 8),
        )
        style.map("TButton", background=[("active", "#EDEDF2"), ("disabled", "#F1F1F4")])
        style.configure(
            "Primary.TButton",
            background=BLUE,
            foreground="#FFFFFF",
            bordercolor=BLUE,
            padding=(14, 9),
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#0066D6"), ("disabled", "#A7CFFF")],
            foreground=[("disabled", "#F7FAFF")],
        )
        style.configure(
            "Finish.TButton",
            background="#30B970",
            foreground="#FFFFFF",
            bordercolor="#30B970",
            padding=(14, 9),
        )
        style.map("Finish.TButton", background=[("active", "#24965A"), ("disabled", "#A9DDC1")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(13, 8), background="#EAEAEE", foreground=MUTED)
        style.map(
            "TNotebook.Tab",
            background=[("selected", SURFACE)],
            foreground=[("selected", INK)],
        )
        style.configure("Treeview", rowheight=28, background=SURFACE, fieldbackground=SURFACE)
        style.configure("Treeview.Heading", font=(FONT, 9, "bold"), padding=(8, 7))
        style.configure("Status.TLabel", background=SURFACE, foreground=MUTED, padding=(12, 10))
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer, style="Surface.TFrame", padding=(20, 15))
        header.pack(fill="x", pady=(0, 12))
        identity = ttk.Frame(header, style="Surface.TFrame")
        identity.pack(side="left")
        ttk.Label(identity, text="PCB INTELLIGENCE · BUILT BY NEXT BUILDER", style="Eyebrow.TLabel").pack(
            anchor="w"
        )
        line = ttk.Frame(identity, style="Surface.TFrame")
        line.pack(anchor="w", pady=(2, 0))
        ttk.Label(line, text="KiCad Astra", style="Title.TLabel").pack(side="left")
        ttk.Label(
            line,
            text=f"  v{VERSION}",
            style="SurfaceMuted.TLabel",
            font=(FONT, 10, "bold"),
        ).pack(side="left", pady=(8, 0))
        journey = ttk.Frame(header, style="Surface.TFrame")
        journey.pack(side="right", padx=(30, 0))
        ttk.Label(
            journey,
            text="ENGINEER-REVIEWED WORKFLOW",
            style="SurfaceMuted.TLabel",
            font=(FONT, 9, "bold"),
        ).pack(anchor="e")
        ttk.Label(
            journey,
            text="Capture  ›  Plan  ›  Inspect  ›  DRC  ›  Apply",
            style="Surface.TLabel",
            font=(FONT, 11),
        ).pack(anchor="e", pady=(4, 0))
        self.buttons = {}
        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(0, 10))
        for key, label, command in [
            ("capture", "Capture board", self._capture),
            ("generate", "Generate plan", self._generate),
            ("drc", "Test with KiCad DRC", self._drc),
            ("revise", "Revise from DRC", self._revise),
            ("apply", "Apply checked plan", self._apply),
            ("export", "Export session", self._export),
            ("import", "Import proposal", self._import),
            ("cancel", "Cancel", self._cancel),
        ]:
            button_style = "Primary.TButton" if key in {"generate", "apply"} else "TButton"
            b = ttk.Button(actions, text=label, command=command, style=button_style)
            b.pack(side="left", padx=(0, 6))
            self.buttons[key] = b
        finish = ttk.Frame(outer)
        finish.pack(fill="x", pady=(0, 12))
        ttk.Label(finish, text="FINISH & FABRICATE", style="Muted.TLabel", font=(FONT, 9, "bold")).pack(
            side="left", padx=(0, 14)
        )
        for key, label, command in [
            ("labels", "Arrange reference labels", self._labels),
            ("manufacture", "Prepare fabrication…", self._manufacture),
        ]:
            button = ttk.Button(finish, text=label, command=command, style="Finish.TButton")
            button.pack(side="left", padx=(0, 8))
            self.buttons[key] = button
        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes, padding=(0, 0, 14, 0))
        panes.add(left, weight=1)
        right = ttk.Frame(panes)
        panes.add(right, weight=4)
        ttk.Label(left, text="OBJECTIVE", font=(FONT, 10, "bold")).pack(
            anchor="w", pady=(4, 7)
        )
        self.request = scrolledtext.ScrolledText(
            left,
            width=32,
            height=10,
            wrap="word",
            font=(FONT, 10),
            background=SURFACE,
            foreground=INK,
            insertbackground=INK,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
        )
        self.request.pack(fill="x")
        self.request.insert(
            "1.0",
            "Improve component placement for compactness and short connections. Preserve connectors and mounting features. Identify missing electrical requirements before proposing sensitive routing.",
        )
        ttk.Label(left, text="Stage").pack(anchor="w", pady=(12, 4))
        ttk.Combobox(left, textvariable=self.mode, values=list(MODES), state="readonly").pack(
            fill="x"
        )
        ttk.Label(left, text="Placement is approved before routing.", style="Muted.TLabel").pack(
            anchor="w", pady=5
        )
        settings = ttk.LabelFrame(left, text="OpenAI API", padding=10)
        settings.pack(fill="x", pady=10)
        for label, var in (("Model", self.model), ("API key (session only)", self.key)):
            ttk.Label(settings, text=label).pack(anchor="w", pady=(5, 3))
            entry = ttk.Entry(settings, textvariable=var, show="•" if var is self.key else "")
            entry.pack(fill="x")
            if var is self.key and os.environ.get("OPENAI_API_KEY"):
                entry.configure(state="disabled")
                ttk.Label(settings, text="OPENAI_API_KEY is set", style="Muted.TLabel").pack(
                    anchor="w"
                )
        ttk.Label(settings, text="Reasoning effort").pack(anchor="w", pady=(8, 3))
        ttk.Combobox(
            settings,
            textvariable=self.effort,
            values=["low", "medium", "high", "xhigh"],
            state="readonly",
        ).pack(fill="x")
        ttk.Checkbutton(
            left,
            text="Send board geometry and design data\nto the OpenAI API",
            variable=self.consent,
        ).pack(anchor="w", pady=6)
        ttk.Label(
            left,
            text="Up to 3 API calls with default revision settings.\nAPI usage is shown in the session report.",
            style="Muted.TLabel",
            wraplength=290,
        ).pack(anchor="w", pady=4)
        self.selection = ttk.Label(
            left, text="Select a footprint in the preview.", wraplength=285, justify="left"
        )
        self.selection.pack(fill="x", pady=15)
        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill="both", expand=True)
        self.preview = BoardPreview(self.notebook, on_select=self._select_ref)
        self.notebook.add(self.preview, text="Board preview")
        changes = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(changes, text="Proposed changes")
        self.changes = ttk.Treeview(changes, columns=("kind", "target", "detail"), show="headings")
        for name, width in (("kind", 100), ("target", 140), ("detail", 500)):
            self.changes.heading(name, text=name.title())
            self.changes.column(name, width=width)
        self.changes.pack(fill="both", expand=True)
        self.validation = self._text_tab("Local checks")
        self.drc_view = self._text_tab("Native DRC")
        self.plan_view = self._text_tab("Session JSON")
        self.quality_view = self._text_tab("Layout quality")
        self.fabrication_view = self._text_tab("Fabrication")
        constraints = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(constraints, text="Constraints")
        bar = ttk.Frame(constraints)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="Check constraints", command=self._check_rules).pack(side="left")
        ttk.Button(bar, text="Load JSON…", command=self._load_rules).pack(side="left", padx=8)
        ttk.Label(
            bar, text="Changes invalidate any previous DRC approval.", style="Muted.TLabel"
        ).pack(side="left")
        self.rules_text = scrolledtext.ScrolledText(constraints, wrap="none", font=(MONO, 10))
        self.rules_text.pack(fill="both", expand=True)
        self.rules_text.insert("1.0", json.dumps(LayoutRules().to_dict(), indent=2))
        self.log_view = self._text_tab("Activity")
        ttk.Label(outer, textvariable=self.status, anchor="w", style="Status.TLabel").pack(
            fill="x", pady=(10, 0)
        )
        self._controls()

    def _text_tab(self, title):
        frame = ttk.Frame(self.notebook, padding=8)
        view = scrolledtext.ScrolledText(
            frame,
            wrap="word",
            font=(MONO, 10),
            state="disabled",
            background=SURFACE,
            foreground=INK,
            relief="flat",
            borderwidth=0,
        )
        view.pack(fill="both", expand=True)
        self.notebook.add(frame, text=title)
        return view

    @staticmethod
    def _text(widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _log(self, value):
        self.log_view.configure(state="normal")
        self.log_view.insert("end", f"[{datetime.now():%H:%M:%S}] {value}\n")
        self.log_view.see("end")
        self.log_view.configure(state="disabled")

    def _controls(self):
        for name, button in self.buttons.items():
            enabled = not self.busy
            if name == "cancel":
                enabled = self.busy
            elif name in {"generate", "labels", "manufacture"}:
                enabled = enabled and self.snapshot is not None
            elif name in {"drc", "export"}:
                enabled = enabled and self.bundle is not None
            elif name == "revise":
                enabled = (
                    enabled
                    and self.receipt is not None
                    and bool(self.receipt.added)
                    and self.bundle is not None
                    and self.bundle.mode != "labels"
                )
            elif name == "apply":
                enabled = (
                    enabled
                    and self.bundle is not None
                    and self.receipt is not None
                    and self.receipt.ok
                )
            if getattr(self.session, "demo", False) and name in {
                "drc",
                "apply",
                "revise",
                "manufacture",
            }:
                enabled = False
            button.configure(state="normal" if enabled else "disabled")

    def _start(self, work, success, message):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        self.status.set(message)
        self._controls()

        def runner():
            try:
                self.events.put(("result", success, work()))
            except BaseException as exc:
                self.events.put(("error", None, exc))

        # Keep process alive until native transactions have unwound on cancellation.
        threading.Thread(target=runner, daemon=False).start()

    def _progress(self, message):
        self.events.put(("progress", None, message))

    def _poll(self):
        try:
            while True:
                kind, callback, value = self.events.get_nowait()
                if kind == "progress":
                    self.status.set(value)
                    self._log(value)
                else:
                    self.busy = False
                    if kind == "error":
                        self.status.set(str(value))
                        self._log(f"{type(value).__name__}: {value}")
                        if not self.closing and not isinstance(value, InterruptedError):
                            messagebox.showerror("KiCad Astra", str(value), parent=self.root)
                    elif not self.closing:
                        try:
                            callback(value)
                        except Exception as exc:
                            self.status.set(str(exc))
                            messagebox.showerror("KiCad Astra", str(exc), parent=self.root)
                    self._controls()
        except queue.Empty:
            pass
        if self.closing and not self.busy:
            self.root.destroy()
            return
        self.root.after(100, self._poll)

    def _cancel(self):
        self.cancel.set()
        self.status.set(
            "Cancellation requested. Waiting for the current API call or native transaction to finish safely…"
        )

    def _close(self):
        if self.busy:
            self.closing = True
            self._cancel()
        else:
            self.root.destroy()

    def _invalidate(self):
        self.bundle = None
        self.receipt = None
        self.changes.delete(*self.changes.get_children())
        for w in (self.validation, self.drc_view, self.plan_view):
            self._text(w, "")
        self._controls()

    def _capture(self):
        if self.busy:
            return
        self.snapshot = None
        self._invalidate()

        def success(snapshot):
            self.snapshot = snapshot
            self.preview.set_scene(snapshot.state)
            self._text(self.quality_view, json.dumps(inspect_quality(snapshot.state), indent=2))
            self._text(
                self.fabrication_view,
                "Save the reviewed board, then prepare fabrication with your verified profile.",
            )
            counts = snapshot.state["counts"]
            self.status.set(
                f"{snapshot.board_path.name} · {counts['footprints']} footprints · {counts['pads']} pads · {counts['nets']} nets"
            )
            self._log("Board captured with KiCad pad polygons and conservative obstacle geometry.")
            self._text(
                self.validation,
                json.dumps(
                    {
                        "geometry_errors": snapshot.state["geometry_errors"],
                        "notes": snapshot.state["warnings"],
                    },
                    indent=2,
                ),
            )
            if getattr(self.session, "demo", False):
                from examples.demo_scene import demo_proposal

                self.mode.set("Routing")
                self._start(
                    lambda: evaluate(
                        demo_proposal(),
                        snapshot,
                        LayoutRules(),
                        "routing",
                        cancel=self.cancel,
                        progress=self._progress,
                    ),
                    self._show_bundle,
                    "Computing an offline demonstration route…",
                )

        self._start(self.session.capture, success, "Reading KiCad geometry…")

    def _labels(self):
        if self.busy or not self.snapshot:
            return
        path = filedialog.askopenfilename(
            title="Optional label style JSON — Cancel uses defaults",
            filetypes=[("Label style", "*.json")],
            parent=self.root,
        )
        try:
            style = (
                LabelStyle(**extract_json(Path(path).read_text(encoding="utf-8"))).checked()
                if path
                else LabelStyle()
            )
            rules = self._rules()
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("Reference labels", str(exc), parent=self.root)
            return
        snapshot = self.snapshot
        self._invalidate()
        self._start(
            lambda: arrange_labels(snapshot, rules, style, cancel=self.cancel),
            self._show_bundle,
            "Arranging visible reference labels…",
        )

    def _manufacture(self):
        if self.busy or not self.snapshot or getattr(self.session, "demo", False):
            return
        from kicad.manufacturing import FabricationProfile, create_package

        profile_file = filedialog.askopenfilename(
            title="Choose fabrication profile JSON",
            filetypes=[("Fabrication profile", "*.json")],
            parent=self.root,
        )
        if not profile_file:
            return
        try:
            profile = FabricationProfile.from_dict(
                extract_json(Path(profile_file).read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("Fabrication profile", str(exc), parent=self.root)
            return
        parent = filedialog.askdirectory(
            title="Choose fabrication output parent folder", parent=self.root
        )
        if not parent:
            return
        snapshot = self.snapshot
        destination = Path(parent) / datetime.now().strftime(
            "kicad-astra-fabrication-%Y%m%d-%H%M%S-%f"
        )

        def work():
            self.session.assert_current(snapshot.fingerprint)
            if snapshot.board_path.read_text(encoding="utf-8").strip() != snapshot.source.strip():
                raise ValueError(
                    "Save the board in KiCad, then capture it again before fabrication."
                )
            binary = self.session.kicad.get_kicad_binary_path(
                "kicad-cli.exe" if os.name == "nt" else "kicad-cli"
            )
            return create_package(
                binary,
                snapshot.board_path,
                destination,
                profile,
                cancel=self.cancel,
                progress=self._progress,
            )

        def success(report):
            self._text(self.fabrication_view, json.dumps(report, indent=2))
            self.notebook.select(self.fabrication_view.master)
            self.status.set(f"Fabrication {report['status']}: {report['output']}")
            self._log(self.status.get())

        self._start(work, success, "Preparing native fabrication preflight…")

    def _rules(self):
        return LayoutRules.from_dict(extract_json(self.rules_text.get("1.0", "end")))

    def _check_rules(self):
        try:
            rules = self._rules()
            if self.bundle and digest(rules.to_dict()) != digest(self.bundle.rules.to_dict()):
                self.receipt = None
                self._controls()
            self.status.set(
                "Constraint syntax is valid. Generate or import a plan to evaluate these settings."
            )
        except Exception as exc:
            messagebox.showerror("Constraints", str(exc), parent=self.root)

    def _load_rules(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(
            filetypes=[("JSON constraints", "*.json")], parent=self.root
        )
        if not path:
            return
        try:
            rules = LayoutRules.load(Path(path))
            self.rules_text.delete("1.0", "end")
            self.rules_text.insert("1.0", json.dumps(rules.to_dict(), indent=2))
            self.receipt = None
            self._controls()
        except Exception as exc:
            messagebox.showerror("Constraints", str(exc), parent=self.root)

    def _generate(self, feedback=None, previous=None):
        if self.busy or not self.snapshot:
            return
        if not self.consent.get():
            messagebox.showinfo(
                "OpenAI API",
                "Enable sending board geometry and design data before requesting a plan.",
                parent=self.root,
            )
            return
        try:
            rules = self._rules()
        except Exception as exc:
            messagebox.showerror("Constraints", str(exc), parent=self.root)
            return
        request = self.request.get("1.0", "end").strip()
        if not request:
            return
        mode = MODES[self.mode.get()]
        model = self.model.get().strip()
        effort = self.effort.get()
        key = self.key.get().strip() or None
        snapshot = self.snapshot
        self._invalidate()

        def work():
            with self.session.lock:
                self.session.assert_current(snapshot.fingerprint)
            client = PlannerClient(api_key=key, model=model, reasoning_effort=effort)
            try:
                return generate(
                    client,
                    snapshot,
                    request,
                    mode,
                    rules,
                    cancel=self.cancel,
                    progress=self._progress,
                    feedback=feedback,
                    previous=previous,
                )
            finally:
                client.close()

        self._start(work, self._show_bundle, "Preparing KiCad Astra request…")

    def _show_bundle(self, bundle):
        self.bundle = bundle
        self.receipt = None
        self.preview.set_scene(bundle.snapshot.state, bundle)
        self.changes.delete(*self.changes.get_children())
        for p in bundle.proposal["placements"]:
            self.changes.insert(
                "",
                "end",
                values=(
                    "Placement",
                    p["reference"],
                    f"{p['x_mm']:.3f}, {p['y_mm']:.3f} mm · {p['rotation_deg']:.1f}° · {p['reason']}",
                ),
            )
        for op in bundle.label_ops:
            self.changes.insert(
                "",
                "end",
                values=(
                    "Reference label",
                    op["reference"],
                    f"{op['x_mm']:.2f}, {op['y_mm']:.2f} mm · {op['height_mm']:.2f} mm height · {op['side']}",
                ),
            )
        pads = {p["id"]: p["label"] for p in bundle.snapshot.state["pads"]}
        for c in bundle.proposal["connections"]:
            self.changes.insert(
                "",
                "end",
                values=(
                    "Connection",
                    c["net"],
                    f"{pads.get(c['from_pad_id'], c['from_pad_id'])} → {pads.get(c['to_pad_id'], c['to_pad_id'])} · {c['reason']}",
                ),
            )
        for f in bundle.proposal["findings"]:
            self.changes.insert(
                "", "end", values=(f["severity"].title(), ", ".join(f["references"]), f["message"])
            )
        for text in bundle.proposal["unresolved"]:
            self.changes.insert("", "end", values=("Unresolved", "", text))
        self._text(self.validation, bundle.report.as_text())
        self._text(self.plan_view, json.dumps(bundle.to_dict(), indent=2))
        self._log(
            f"Plan compiled: {len(bundle.routes)} connections; {len(bundle.report.errors)} local errors; usage {bundle.usage}."
        )
        self.status.set(
            "Inspect the proposal, then test with KiCad DRC."
            if bundle.report.ok and bundle.has_changes
            else "Review findings and local checks. No changes can be applied yet."
        )
        self._controls()

    def _check_bundle_rules(self):
        if not self.bundle:
            raise ValueError("Generate or import a plan first.")
        if self._rules().to_dict() != self.bundle.rules.to_dict():
            self.receipt = None
            self._controls()
            raise ValueError(
                "Constraints changed. Generate or import the proposal again before DRC/apply."
            )

    def _drc(self):
        try:
            self._check_bundle_rules()
        except Exception as exc:
            messagebox.showerror("Native DRC", str(exc), parent=self.root)
            return
        bundle = self.bundle
        self.receipt = None

        def success(receipt):
            self.receipt = receipt
            self._text(self.drc_view, json.dumps(receipt.to_dict(), indent=2))
            self.status.set(
                f"Native DRC: {len(receipt.added)} new issues; {receipt.candidate.violation_count} total remaining. "
                + (
                    "Ready for review and apply."
                    if receipt.ok
                    else "Revise the plan or adjust constraints."
                )
            )
            self._log(self.status.get())

        self._start(
            lambda: preview_drc(self.session, bundle, cancel=self.cancel, progress=self._progress),
            success,
            "Native preflight briefly stages the proposal and restores the live board before CLI checks…",
        )

    def _revise(self):
        if self.receipt and self.bundle:
            feedback = {
                "native_drc": self.receipt.to_dict(),
                "local_checks": self.bundle.report.to_dict(),
            }
            previous = self.bundle.proposal
            self._generate(feedback, previous)

    def _apply(self):
        try:
            self._check_bundle_rules()
        except Exception as exc:
            messagebox.showerror("Apply", str(exc), parent=self.root)
            return
        if not self.receipt or not self.receipt.ok:
            return
        bundle, receipt = self.bundle, self.receipt
        if not messagebox.askyesno(
            "Apply checked plan",
            f"Apply {len(bundle.proposal['placements'])} placements and {len(bundle.routes)} connections and {len(bundle.label_ops)} reference labels?\n\n"
            f"Native DRC found no new reported issues. {receipt.candidate.violation_count} existing issues remain.\n"
            "A backup is created first. Changes form one KiCad undo step; save the board after review.",
            parent=self.root,
        ):
            return

        def success(result):
            self._log(json.dumps(result))
            self.receipt = None
            self.status.set(
                f"Applied. Backup: {result['backup']}. Capture a new board before the next stage."
            )
            if result.get("audit_warning"):
                messagebox.showwarning("Applied", result["audit_warning"], parent=self.root)
            self._controls()

        self._start(
            lambda: apply_checked(self.session, bundle, receipt),
            success,
            "Applying the checked native operations…",
        )

    def _export(self):
        if not self.bundle:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile="kicad-astra-session.json",
            filetypes=[("Session report", "*.json")],
            parent=self.root,
        )
        if not path:
            return
        try:
            data = self.bundle.to_dict()
            if self.receipt:
                data["native_drc"] = self.receipt.to_dict()
            Path(path).write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
            self._log(f"Exported session to {path}")
        except Exception as exc:
            messagebox.showerror("Export", str(exc), parent=self.root)

    def _import(self):
        if not self.snapshot or self.busy:
            messagebox.showinfo("Import", "Capture the active board first.", parent=self.root)
            return
        path = filedialog.askopenfilename(
            filetypes=[("KiCad Astra JSON", "*.json")], parent=self.root
        )
        if not path:
            return
        try:
            if Path(path).stat().st_size > 2_000_000:
                raise ValueError("Import exceeds 2 MB.")
            data = extract_json(Path(path).read_text(encoding="utf-8"))
            if "proposal" in data:
                if data.get("source_fingerprint") != self.snapshot.fingerprint:
                    raise ValueError("Imported session belongs to a different board revision.")
                proposal = data["proposal"]
                mode = data["mode"]
                if mode == "labels" or data.get("label_ops"):
                    raise ValueError(
                        "Generate reference labels locally from a fresh capture; label sessions are reports only."
                    )
            else:
                proposal = data
                mode = MODES[self.mode.get()]
            rules = self._rules()
            snapshot = self.snapshot
            self._invalidate()
            # Imported routes and DRC receipts are deliberately never trusted.
            self._start(
                lambda: evaluate(
                    proposal, snapshot, rules, mode, cancel=self.cancel, progress=self._progress
                ),
                self._show_bundle,
                "Checking imported proposal and rebuilding routes locally…",
            )
        except Exception as exc:
            messagebox.showerror("Import", str(exc), parent=self.root)

    def _select_ref(self, ref):
        if not self.snapshot:
            return
        fp = next(f for f in self.snapshot.state["footprints"] if f["reference"] == ref)
        pads = [p for p in self.snapshot.state["pads"] if p["reference"] == ref]
        self.selection.configure(
            text=f"{ref} · {fp['value']}\n{fp['side']} · {fp['rotation_deg']:.1f}°\n"
            + "\n".join(f"{p['label']} — {p['net'] or 'unassigned'}" for p in pads[:12])
        )
