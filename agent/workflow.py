"""Bounded plan → geometry/router → measured revision workflow."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.tools import PlanFormatError, normalize_plan
from kicad.board_reader import BoardSnapshot, digest
from kicad.config import LayoutRules
from kicad.router import RoutingError, compile_connections
from kicad.validation import ValidationReport, validate_plan


@dataclass
class PlanBundle:
    snapshot: BoardSnapshot
    proposal: dict
    routes: list
    rules: LayoutRules
    report: ValidationReport
    mode: str
    history: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    label_ops: list = field(default_factory=list)

    @property
    def fingerprint(self):
        return self.snapshot.fingerprint

    @property
    def has_changes(self):
        return bool(self.proposal["placements"] or self.routes or self.label_ops)

    def content_hash(self):
        return digest(
            {
                "source": self.fingerprint,
                "proposal": self.proposal,
                "routes": self.routes,
                "rules": self.rules.to_dict(),
                "mode": self.mode,
                "label_ops": self.label_ops,
            }
        )

    def to_dict(self):
        return {
            "format": "kicad-astra-session-v2",
            "source_fingerprint": self.fingerprint,
            "bundle_hash": self.content_hash(),
            "proposal": self.proposal,
            "compiled_routes": self.routes,
            "rules": self.rules.to_dict(),
            "local_validation": self.report.to_dict(),
            "mode": self.mode,
            "label_ops": self.label_ops,
            "revision_history": self.history,
            "api_usage": self.usage,
        }


def evaluate(proposal, snapshot, rules, mode, *, cancel=None, progress=None):
    proposal = normalize_plan(proposal, mode)
    report = validate_plan(proposal, snapshot.state, rules)
    routes = []
    if report.ok and proposal["connections"]:
        try:
            routes, failures = compile_connections(
                proposal["connections"],
                snapshot.state,
                rules,
                seed=snapshot.fingerprint,
                cancel=cancel,
                progress=progress,
            )
        except RoutingError as exc:
            failures = [str(exc)]
        report = validate_plan(proposal, snapshot.state, rules, routes)
        report.errors.extend(failures)
        if len(routes) != len(proposal["connections"]) and not failures:
            report.errors.append("Not every requested connection produced a complete route.")
    return PlanBundle(
        snapshot, proposal, routes, LayoutRules.from_dict(rules.to_dict()), report, mode
    )


def generate(
    client,
    snapshot,
    request,
    mode,
    rules,
    *,
    cancel=None,
    progress=None,
    feedback=None,
    previous=None,
):
    rules.checked()
    history = []
    seen = set()
    bundle = None
    initial_pairs = {
        tuple(sorted((c["from_pad_id"], c["to_pad_id"])))
        for c in (previous or {}).get("connections", [])
    }
    for attempt in range(rules.max_revisions + 1):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Planning cancelled.")
        if progress:
            progress(f"KiCad Astra proposal {attempt + 1}/{rules.max_revisions + 1}…")
        try:
            proposal = client.create_plan(
                board_state=snapshot.model_packet(),
                request=request,
                mode=mode,
                rules=rules.to_dict(),
                feedback=feedback,
                previous_plan=previous,
                cancel=cancel,
            )
        except PlanFormatError as exc:
            history.append({"attempt": attempt + 1, "schema_error": str(exc)})
            feedback = {"schema_error": str(exc)}
            if attempt == rules.max_revisions:
                raise
            continue
        key = digest(proposal)
        if key in seen:
            if bundle:
                bundle.report.warnings.append(
                    "Revision stopped: KiCad Astra repeated an unchanged proposal."
                )
                break
        seen.add(key)
        bundle = evaluate(proposal, snapshot, rules, mode, cancel=cancel, progress=progress)
        current_pairs = {
            tuple(sorted((c["from_pad_id"], c["to_pad_id"]))) for c in proposal["connections"]
        }
        if not initial_pairs:
            initial_pairs = current_pairs
        missing = initial_pairs - current_pairs
        if missing:
            bundle.report.errors.append(
                f"The revision dropped {len(missing)} requested connections. Start a new scoped request to intentionally omit them."
            )
        history.append(
            {"attempt": attempt + 1, "proposal_hash": key, "validation": bundle.report.to_dict()}
        )
        if bundle.report.ok:
            break
        feedback = {
            "local_validation": bundle.report.to_dict(),
            "previous_drc_feedback": feedback if attempt == 0 else None,
        }
        previous = proposal
    if bundle is None:
        raise RuntimeError("No complete proposal was generated.")
    bundle.history = history
    bundle.usage = dict(client.usage)
    return bundle
