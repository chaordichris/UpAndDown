"""Machine-checkable phase gate reviews."""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.backtest.summary import BacktestAggregateSummary
from src.config import get_settings
from src.monitoring.reports import StoredPaperTradeReport, build_stored_paper_trade_report
from src.risk.ror import RiskOfRuinEstimate, estimate_risk_of_ruin
from src.storage.db import get_session, init_db
from src.storage.hashing import artifact_hash
from src.storage.models import CLVSnapshot


@dataclass(frozen=True)
class GateCriterion:
    """One pass/fail criterion in a phase gate."""

    name: str
    passed: bool
    observed: str
    required: str


@dataclass(frozen=True)
class PhaseGateResult:
    """Full gate result for one phase transition."""

    phase: str
    passed: bool
    criteria: list[GateCriterion]


def evaluate_phase3_gate(
    *,
    report: StoredPaperTradeReport,
    clv_values: list[float],
    paper_tournaments: int,
    pipeline_crashes: int,
    data_completeness: float,
    ror_estimate: RiskOfRuinEstimate,
    clv_bootstrap_seed: int,
) -> PhaseGateResult:
    """Evaluate the pre-committed Phase 3 -> 4 paper-trading gate."""
    average_clv = report.average_clv_raw
    clv_lower_bound = bootstrap_mean_lower_bound(
        clv_values,
        confidence=0.90,
        simulations=2_000,
        seed=clv_bootstrap_seed,
    )
    criteria = [
        GateCriterion(
            name="paper_tournaments",
            passed=paper_tournaments >= 4,
            observed=str(paper_tournaments),
            required=">= 4",
        ),
        GateCriterion(
            name="settled_bets",
            passed=report.settled_count >= 60,
            observed=str(report.settled_count),
            required=">= 60",
        ),
        GateCriterion(
            name="aggregate_clv",
            passed=average_clv is not None and average_clv >= 0,
            observed=_format_optional_pct(average_clv),
            required=">= 0.00%",
        ),
        GateCriterion(
            name="clv_90ci_lower_bound",
            passed=clv_lower_bound is not None and clv_lower_bound >= -0.005,
            observed=_format_optional_pct(clv_lower_bound),
            required=">= -0.50%",
        ),
        GateCriterion(
            name="pipeline_crashes",
            passed=pipeline_crashes == 0,
            observed=str(pipeline_crashes),
            required="0",
        ),
        GateCriterion(
            name="data_completeness",
            passed=data_completeness >= 0.95,
            observed=f"{data_completeness:.2%}",
            required=">= 95.00%",
        ),
        GateCriterion(
            name="ror_paper_only_probability",
            passed=ror_estimate.paper_only_probability <= 0.05,
            observed=f"{ror_estimate.paper_only_probability:.2%}",
            required="<= 5.00%",
        ),
    ]
    return PhaseGateResult(
        phase="phase3_to_phase4",
        passed=all(criterion.passed for criterion in criteria),
        criteria=criteria,
    )


def bootstrap_mean_lower_bound(
    values: list[float],
    *,
    confidence: float,
    simulations: int,
    seed: int,
) -> float | None:
    """Return a deterministic lower confidence bound for the sample mean."""
    if not values:
        return None
    if not 0 < confidence < 1:
        raise ValueError("confidence must be in (0, 1).")
    if simulations <= 0:
        raise ValueError("simulations must be positive.")

    rng = random.Random(seed)
    means = []
    for _ in range(simulations):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(sum(sample) / len(sample))
    means.sort()
    lower_tail = (1.0 - confidence) / 2.0
    index = max(0, int(lower_tail * simulations) - 1)
    return means[index]


def render_phase_gate_result(result: PhaseGateResult) -> str:
    """Render a phase-gate result for terminal review."""
    lines = [f"Phase gate: {result.phase}", f"Status: {'PASS' if result.passed else 'FAIL'}"]
    for criterion in result.criteria:
        status = "PASS" if criterion.passed else "FAIL"
        lines.append(
            f"{status} {criterion.name}: observed {criterion.observed}, required {criterion.required}"
        )
    return "\n".join(lines)


def phase_gate_result_payload(result: PhaseGateResult) -> dict[str, Any]:
    """Return a JSON-compatible phase-gate result payload."""
    return {
        "phase": result.phase,
        "passed": result.passed,
        "criteria": [asdict(criterion) for criterion in result.criteria],
    }


def build_phase_gate_artifact(
    *,
    result: PhaseGateResult,
    report: StoredPaperTradeReport,
    clv_values: list[float],
    ror_estimate: RiskOfRuinEstimate,
    operator_inputs: dict[str, Any],
    config: dict[str, Any],
    backtest_summary: BacktestAggregateSummary | dict[str, Any] | None = None,
    code_version: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic JSON artifact for an audited phase-gate review."""
    metrics: dict[str, Any] = {
        "report": asdict(report),
        "clv_count": len(clv_values),
        "ror_estimate": asdict(ror_estimate),
    }
    if backtest_summary is not None:
        metrics["backtest_summary"] = _backtest_summary_payload(backtest_summary)

    payload = {
        "artifact_type": "phase_gate_review",
        "result": phase_gate_result_payload(result),
        "operator_inputs": operator_inputs,
        "config": config,
        "metrics": metrics,
    }
    return {
        **payload,
        "artifact_hash": artifact_hash(
            artifact_type="phase_gate_review",
            inputs={
                "result": payload["result"],
                "operator_inputs": operator_inputs,
                "metrics": payload["metrics"],
            },
            config=config,
            code_version=code_version,
        ),
    }


def render_phase_gate_artifact_json(artifact: dict[str, Any]) -> str:
    """Render a phase-gate artifact as stable, human-readable JSON."""
    return json.dumps(artifact, sort_keys=True, indent=2)


def write_output(path: Path | None, content: str) -> None:
    """Write rendered output when an operator requests an artifact file."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def collect_clv_values(session: Session) -> list[float]:
    """Load non-null raw CLV values from the paper-trading DB."""
    return [
        row.clv_raw
        for row in session.query(CLVSnapshot).order_by(CLVSnapshot.clv_id).all()
        if row.clv_raw is not None
    ]


def load_backtest_summary_artifact(path: Path) -> dict[str, Any]:
    """Load a WS-7 summary artifact for inclusion in a phase review."""
    with path.open() as file:
        payload = json.load(file)
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("backtest summary artifact must contain a summary object.")
    return {
        "artifact_file": path.name,
        "summary": summary,
        "summary_hash": payload.get("summary_hash"),
        "manifest_hash": payload.get("manifest_hash"),
    }


def run_phase3_check(args: argparse.Namespace) -> PhaseGateResult:
    return run_phase3_check_artifact(args)["result_obj"]


def run_phase3_check_artifact(
    args: argparse.Namespace,
    *,
    code_version: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    init_db(args.database_url)
    with get_session(args.database_url) as session:
        report = build_stored_paper_trade_report(session)
        clv_values = collect_clv_values(session)
    backtest_summary = (
        load_backtest_summary_artifact(Path(args.backtest_summary_json))
        if args.backtest_summary_json
        else None
    )

    ror_estimate = estimate_risk_of_ruin(
        starting_bankroll=args.starting_bankroll,
        peak_bankroll=args.peak_bankroll,
        bet_count=settings.ror.bet_count,
        simulations=settings.ror.simulations,
        stake_fraction=args.stake_fraction,
        expected_return_per_staked_dollar=args.expected_return,
        return_sd_per_staked_dollar=args.return_sd,
        paper_only_threshold=settings.drawdown.paper_only_threshold,
        halt_threshold=settings.drawdown.halt_threshold,
        seed=settings.ror.seed,
    )
    result = evaluate_phase3_gate(
        report=report,
        clv_values=clv_values,
        paper_tournaments=args.paper_tournaments,
        pipeline_crashes=args.pipeline_crashes,
        data_completeness=args.data_completeness,
        ror_estimate=ror_estimate,
        clv_bootstrap_seed=settings.ror.seed,
    )
    operator_inputs = {
        "paper_tournaments": args.paper_tournaments,
        "pipeline_crashes": args.pipeline_crashes,
        "data_completeness": args.data_completeness,
        "starting_bankroll": args.starting_bankroll,
        "peak_bankroll": args.peak_bankroll,
        "stake_fraction": args.stake_fraction,
        "expected_return": args.expected_return,
        "return_sd": args.return_sd,
    }
    config = {
        "ror": {
            "bet_count": settings.ror.bet_count,
            "simulations": settings.ror.simulations,
            "seed": settings.ror.seed,
        },
        "drawdown": {
            "paper_only_threshold": settings.drawdown.paper_only_threshold,
            "halt_threshold": settings.drawdown.halt_threshold,
        },
        "clv_bootstrap": {
            "confidence": 0.90,
            "simulations": 2_000,
            "seed": settings.ror.seed,
        },
    }
    artifact = build_phase_gate_artifact(
        result=result,
        report=report,
        clv_values=clv_values,
        ror_estimate=ror_estimate,
        operator_inputs=operator_inputs,
        config=config,
        backtest_summary=backtest_summary,
        code_version=code_version,
    )
    return {**artifact, "result_obj": result}


def _format_optional_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def _backtest_summary_payload(
    summary: BacktestAggregateSummary | dict[str, Any],
) -> dict[str, Any]:
    if isinstance(summary, BacktestAggregateSummary):
        return asdict(summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate quantitative phase gates.")
    parser.add_argument("--phase", choices=["phase3"], default="phase3")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--paper-tournaments", type=int, required=True)
    parser.add_argument("--pipeline-crashes", type=int, required=True)
    parser.add_argument("--data-completeness", type=float, required=True)
    parser.add_argument("--starting-bankroll", type=float, required=True)
    parser.add_argument("--peak-bankroll", type=float, required=True)
    parser.add_argument("--stake-fraction", type=float, required=True)
    parser.add_argument("--expected-return", type=float, required=True)
    parser.add_argument("--return-sd", type=float, required=True)
    parser.add_argument(
        "--backtest-summary-json",
        help="Optional WS-7 summary artifact JSON to attach to the phase review.",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--output", type=Path, help="Optional path to write the rendered result.")
    parser.add_argument("--code-version", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    artifact = run_phase3_check_artifact(args, code_version=args.code_version)
    result = artifact["result_obj"]
    if args.format == "json":
        artifact = {key: value for key, value in artifact.items() if key != "result_obj"}
        rendered = render_phase_gate_artifact_json(artifact)
    else:
        rendered = render_phase_gate_result(result)
    write_output(args.output, rendered)
    print(rendered)
    raise SystemExit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
