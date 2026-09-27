"""
bobthereviewer.pipeline
~~~~~~~~~~~~~~~~~~~~~~~
The shared analysis + execution pipeline.

This module orchestrates Lane 1 analysis (triage, changed functions, caller
tracing) and delegates execution to Lane 2's executor when available.

Design principles:
- Returns structured results; never prints, never calls sys.exit().
- Emits progress via a callback (step, status, message) → None.
- The same pipeline function is used by the CLI, the local API server,
  and tests.
- A run_id is allocated once and passed through; callers (CLI, server)
  may allocate it in advance.

Execution boundary:
  Lane 1 produces a WorktreeContext and an AnalysisResult.
  Lane 2 receives these plus a ProbeSpec and returns an ExecutionResult.
  Lane 1 assembles the final evidence dict and validates it.

Lane 2 integration:
  When bobthereviewer.executor is importable, it is called.
  When not available, execution fields in the evidence are set to their
  analysis-only defaults (empty test_results, empty probe_results).
  The pending integration is documented rather than fabricated.

Ownership: Lane 1.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from bobthereviewer.analysis import analyze, changed_function_to_dict
from bobthereviewer.contracts import validate_evidence
from bobthereviewer.snapshots import WorktreeContext, WorktreeManager
from bobthereviewer.triage import TriageResult, classify

# Progress callback type: (step, status, message) → None
ProgressCallback = Callable[[str, str, str], None]

_NOOP: ProgressCallback = lambda step, status, msg: None


# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------

@dataclass
class ProbeSpec:
    """Specifies which probe files to run.  Owned by the caller (CLI / API)."""
    probe_files: list[str] = field(default_factory=list)
    prior_run_id: str | None = None
    prior_report_path: Path | None = None


@dataclass
class ExecutionResult:
    """Structured return from Lane 2's executor.

    When the executor is unavailable, all fields are at their zero values.
    """
    test_results: dict = field(default_factory=lambda: {"base": {}, "head": {}})
    probe_results: list[dict] = field(default_factory=list)
    frozen_suite_hash: str | None = None
    uncovered_callers: list[str] = field(default_factory=list)
    execution_notes: list[str] = field(default_factory=list)


@dataclass
class PipelineResult:
    """Final output of the pipeline: a validated evidence dict plus save path."""
    evidence: dict
    run_id: str
    output_path: Path | None  # where evidence.json was written, or None (analyze mode)


# ---------------------------------------------------------------------------
# Lane 2 executor integration
# ---------------------------------------------------------------------------

def _call_executor(
    ctx: WorktreeContext,
    analysis_result,
    probe_spec: ProbeSpec,
    triage: TriageResult,
    run_id: str,
    callback: ProgressCallback,
    config: dict | None = None,
    src_layout: bool = False,
) -> ExecutionResult:
    """Call Lane 2's executor if available; return an empty result otherwise."""
    try:
        from bobthereviewer import executor as _executor  # type: ignore[import]

        prior_report = None
        if probe_spec.prior_report_path:
            p = Path(probe_spec.prior_report_path)
            if not p.is_absolute() and getattr(ctx, "repo_root", None):
                p = ctx.repo_root / p
            if p.exists():
                try:
                    import json
                    prior_report = json.loads(p.read_text(encoding="utf-8"))
                    if not probe_spec.prior_run_id and isinstance(prior_report, dict):
                        probe_spec.prior_run_id = prior_report.get("run_id")
                except Exception:
                    pass

        return _executor.run(
            ctx=ctx,
            analysis_result=analysis_result,
            probe_spec=probe_spec,
            triage=triage,
            run_id=run_id,
            callback=callback,
            config=config,
            prior_report=prior_report,
            src_layout=src_layout,
        )
    except ImportError:
        # Lane 2 not yet available — document the pending integration
        return ExecutionResult(
            execution_notes=[
                "Execution pending: bobthereviewer.executor (Lane 2) is not yet available. "
                "Install Lane 2's implementation to run tests and probes."
            ]
        )


# ---------------------------------------------------------------------------
# Evidence assembly
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _assemble_evidence(
    run_id: str,
    ctx: WorktreeContext,
    triage: TriageResult,
    analysis_result,
    exec_result: ExecutionResult,
    probe_spec: ProbeSpec,
    ci_run_url: str | None = None,
) -> dict:
    """Build the evidence dict from pipeline results."""
    return {
        "schema_version": "1",
        "run_id": run_id,
        "generated_at": _now_iso(),
        "repository": ctx.repository_url,
        "base_ref": ctx.base_ref,
        "head_ref": ctx.head_ref,
        "base_commit": ctx.base_commit,
        "head_commit": ctx.head_commit,
        "prior_run_id": probe_spec.prior_run_id,
        "ci_run_url": ci_run_url,
        "frozen_suite_hash": exec_result.frozen_suite_hash,
        "triage": {
            "category": triage.category,
            "skipped": triage.skipped,
            "skip_reason": triage.skip_reason,
        },
        "analysis_limits": {
            **analysis_result.analysis_limits,
            "notes": [
                *analysis_result.analysis_limits.get("notes", []),
                *exec_result.execution_notes,
            ],
        },
        "changed_functions": [
            changed_function_to_dict(cf)
            for cf in analysis_result.changed_functions
        ],
        "test_results": exec_result.test_results,
        "probe_results": exec_result.probe_results,
        "decisions": _load_approved_decisions(ctx, analysis_result),
    }


def _load_approved_decisions(ctx: WorktreeContext, analysis_result) -> list[dict]:
    """Load matching approved decisions from .bobreviewer/decisions/."""
    decisions: list[dict] = []
    try:
        from bobthereviewer.decisions import lookup
        decisions_dir = ctx.repo_root / ".bobreviewer" / "decisions"
        if decisions_dir.exists():
            seen: set[tuple] = set()
            for cf in analysis_result.changed_functions:
                matches = lookup(
                    repo=ctx.repository_url,
                    file_path=cf.file_path,
                    symbol=cf.symbol,
                    default_branch=ctx.base_ref,
                    decisions_dir=decisions_dir,
                )
                for d in matches:
                    key = (d.get("symbol"), d.get("head_commit"), d.get("case_id"))
                    if key not in seen:
                        seen.add(key)
                        decisions.append(d)
    except Exception:
        pass
    return decisions


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def run_analysis_pipeline(
    repo_dir: Path,
    base_ref: str,
    head_ref: str,
    probe_spec: ProbeSpec | None = None,
    run_id: str | None = None,
    execute: bool = True,
    force_run: bool = False,
    output_dir: Path | None = None,
    ci_run_url: str | None = None,
    callback: ProgressCallback = _NOOP,
) -> PipelineResult:
    """Run the full analysis (and optionally execution) pipeline.

    Parameters
    ----------
    repo_dir:
        Starting directory for repository root resolution.
    base_ref, head_ref:
        Git refs to compare.
    probe_spec:
        Which probes to run.  If None, uses an empty spec (no probes).
    run_id:
        Pre-allocated UUID string.  If None, a new UUID is generated.
    execute:
        When False, stops after analysis (triage + changed functions +
        callers).  Equivalent to the ``analyze`` subcommand.
    force_run:
        When True, overrides docs-only skip logic.
    output_dir:
        Directory to write evidence.json into.  If None, evidence is
        returned but not written to disk.
    ci_run_url:
        CI run URL to embed in evidence.
    callback:
        Progress callback.  Called as callback(step, status, message).

    Returns
    -------
    PipelineResult with a validated evidence dict.
    """
    if probe_spec is None:
        probe_spec = ProbeSpec()
    if run_id is None:
        run_id = str(uuid.uuid4())

    callback("triage", "started", "Resolving refs and classifying diff")

    with WorktreeManager(repo_dir, base_ref, head_ref) as ctx:
        # ---- Config & Layout ----
        config = None
        config_path = ctx.repo_root / ".bobreviewer" / "config.json"
        if config_path.exists():
            try:
                import json
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        src_layout = False
        try:
            from bobthereviewer.executor import _has_src_package
            src_layout = _has_src_package(ctx.base_path) or _has_src_package(ctx.head_path)
        except Exception:
            pass

        # ---- Triage ----
        triage = classify(
            ctx.changed_files,
            ctx.base_path,
            ctx.head_path,
            force_run=force_run,
        )
        callback("triage", "completed", f"Category: {triage.category}")

        # ---- Analysis ----
        callback("analyze", "started", "Parsing ASTs and tracing callers")
        analysis_result = analyze(ctx.base_path, ctx.head_path, ctx.changed_files)
        callback("analyze", "completed",
                 f"{len(analysis_result.changed_functions)} changed function(s) found")

        # ---- Execution ----
        if execute and not triage.skipped:
            exec_result = _call_executor(
                ctx, analysis_result, probe_spec, triage, run_id, callback,
                config=config, src_layout=src_layout,
            )
        else:
            exec_result = ExecutionResult()

        # ---- Assemble evidence ----
        evidence = _assemble_evidence(
            run_id=run_id,
            ctx=ctx,
            triage=triage,
            analysis_result=analysis_result,
            exec_result=exec_result,
            probe_spec=probe_spec,
            ci_run_url=ci_run_url,
        )

    # Validate before writing
    validate_evidence(evidence)

    # Write to disk if requested
    output_path: Path | None = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "evidence.json"
        import json
        output_path.write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    callback("done", "completed", f"Run {run_id} complete")

    return PipelineResult(evidence=evidence, run_id=run_id, output_path=output_path)
