from __future__ import annotations

import json
from pathlib import Path

from scripts.phase_gate_check import (
    bootstrap_mean_lower_bound,
    build_phase_gate_artifact,
    evaluate_phase3_gate,
    load_backtest_summary_artifact,
    render_phase_gate_artifact_json,
    render_phase_gate_result,
    write_output,
)
from src.monitoring.reports import StoredPaperTradeReport
from src.risk.ror import RiskOfRuinEstimate


def test_phase3_gate_passes_when_all_criteria_clear() -> None:
    result = evaluate_phase3_gate(
        report=_report(settled_count=60, average_clv_raw=0.01),
        clv_values=[0.01] * 60,
        paper_tournaments=4,
        pipeline_crashes=0,
        data_completeness=0.95,
        ror_estimate=_ror(paper_only_probability=0.05),
        clv_bootstrap_seed=7,
    )

    assert result.passed
    assert all(criterion.passed for criterion in result.criteria)


def test_phase3_gate_fails_each_missing_requirement() -> None:
    result = evaluate_phase3_gate(
        report=_report(settled_count=59, average_clv_raw=-0.001),
        clv_values=[-0.01] * 59,
        paper_tournaments=3,
        pipeline_crashes=1,
        data_completeness=0.94,
        ror_estimate=_ror(paper_only_probability=0.06),
        clv_bootstrap_seed=7,
    )

    failed = {criterion.name for criterion in result.criteria if not criterion.passed}
    assert failed == {
        "paper_tournaments",
        "settled_bets",
        "aggregate_clv",
        "clv_90ci_lower_bound",
        "pipeline_crashes",
        "data_completeness",
        "ror_paper_only_probability",
    }


def test_phase3_gate_fails_without_clv_values() -> None:
    result = evaluate_phase3_gate(
        report=_report(settled_count=60, average_clv_raw=None),
        clv_values=[],
        paper_tournaments=4,
        pipeline_crashes=0,
        data_completeness=0.99,
        ror_estimate=_ror(paper_only_probability=0.01),
        clv_bootstrap_seed=7,
    )

    failed = {criterion.name for criterion in result.criteria if not criterion.passed}
    assert failed == {"aggregate_clv", "clv_90ci_lower_bound"}


def test_bootstrap_lower_bound_is_reproducible() -> None:
    first = bootstrap_mean_lower_bound(
        [0.01, 0.02, -0.005, 0.015],
        confidence=0.90,
        simulations=500,
        seed=11,
    )
    second = bootstrap_mean_lower_bound(
        [0.01, 0.02, -0.005, 0.015],
        confidence=0.90,
        simulations=500,
        seed=11,
    )

    assert first == second


def test_render_phase_gate_result_marks_failures() -> None:
    result = evaluate_phase3_gate(
        report=_report(settled_count=59, average_clv_raw=0.01),
        clv_values=[0.01] * 59,
        paper_tournaments=4,
        pipeline_crashes=0,
        data_completeness=0.99,
        ror_estimate=_ror(paper_only_probability=0.01),
        clv_bootstrap_seed=7,
    )

    rendered = render_phase_gate_result(result)
    assert "Status: FAIL" in rendered
    assert "FAIL settled_bets" in rendered


def test_phase_gate_artifact_is_stable_json_with_hash() -> None:
    result = evaluate_phase3_gate(
        report=_report(settled_count=60, average_clv_raw=0.01),
        clv_values=[0.01] * 60,
        paper_tournaments=4,
        pipeline_crashes=0,
        data_completeness=0.95,
        ror_estimate=_ror(paper_only_probability=0.05),
        clv_bootstrap_seed=7,
    )
    kwargs = {
        "result": result,
        "report": _report(settled_count=60, average_clv_raw=0.01),
        "clv_values": [0.01] * 60,
        "ror_estimate": _ror(paper_only_probability=0.05),
        "operator_inputs": {
            "paper_tournaments": 4,
            "pipeline_crashes": 0,
            "data_completeness": 0.95,
        },
        "config": {
            "ror": {"bet_count": 100, "simulations": 100, "seed": 7},
            "clv_bootstrap": {"confidence": 0.90, "simulations": 2_000, "seed": 7},
        },
        "code_version": "phase-gate-test",
    }

    first = build_phase_gate_artifact(**kwargs)
    second = build_phase_gate_artifact(**kwargs)
    rendered = render_phase_gate_artifact_json(first)

    assert first == second
    assert first["artifact_hash"] == "215677f76c666f33bf5ef5e6bf54ce8e4d65782bb3d7e73f79a7f8f4e94cdb36"
    assert '"artifact_hash":' in rendered
    assert '"phase": "phase3_to_phase4"' in rendered


def test_phase_gate_artifact_can_include_backtest_summary() -> None:
    result = evaluate_phase3_gate(
        report=_report(settled_count=60, average_clv_raw=0.01),
        clv_values=[0.01] * 60,
        paper_tournaments=4,
        pipeline_crashes=0,
        data_completeness=0.95,
        ror_estimate=_ror(paper_only_probability=0.05),
        clv_bootstrap_seed=7,
    )
    backtest_summary = {
        "artifact_file": "backtest-review.json",
        "summary": {
            "tournament_count": 2,
            "settled_count": 3,
            "average_clv_raw": 0.0,
        },
        "summary_hash": "summary-hash",
        "manifest_hash": "manifest-hash",
    }

    artifact = build_phase_gate_artifact(
        result=result,
        report=_report(settled_count=60, average_clv_raw=0.01),
        clv_values=[0.01] * 60,
        ror_estimate=_ror(paper_only_probability=0.05),
        operator_inputs={
            "paper_tournaments": 4,
            "pipeline_crashes": 0,
            "data_completeness": 0.95,
        },
        config={"ror": {"bet_count": 100, "simulations": 100, "seed": 7}},
        backtest_summary=backtest_summary,
        code_version="phase-gate-backtest-test",
    )

    assert artifact["metrics"]["backtest_summary"] == backtest_summary
    assert artifact["artifact_hash"] == "aea75acfd3ef1850e31a361513e23f9fa821d89dbfc424ae089e2ce584b8a7c8"


def test_load_backtest_summary_artifact(tmp_path: Path) -> None:
    path = tmp_path / "backtest-summary.json"
    path.write_text(
        json.dumps(
            {
                "summary": {"tournament_count": 2, "settled_count": 3},
                "summary_hash": "summary-hash",
                "manifest_hash": "manifest-hash",
            }
        )
    )

    loaded = load_backtest_summary_artifact(path)

    assert loaded == {
        "artifact_file": "backtest-summary.json",
        "summary": {"tournament_count": 2, "settled_count": 3},
        "summary_hash": "summary-hash",
        "manifest_hash": "manifest-hash",
    }


def test_write_output_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "artifacts" / "phase-gate.json"

    write_output(path, '{"passed": false}')

    assert path.read_text() == '{"passed": false}'


def _report(*, settled_count: int, average_clv_raw: float | None) -> StoredPaperTradeReport:
    return StoredPaperTradeReport(
        ticket_count=settled_count,
        approved_count=settled_count,
        open_ticket_count=0,
        placed_count=settled_count,
        settled_count=settled_count,
        pending_settlement_count=0,
        clv_count=0 if average_clv_raw is None else settled_count,
        missing_clv_count=0 if average_clv_raw is not None else settled_count,
        total_staked=10_000.0,
        open_approved_stake=0.0,
        total_profit_loss=100.0,
        strategy_profit_loss=100.0,
        promo_profit_loss=0.0,
        roi=0.01,
        strategy_roi=0.01,
        average_edge=0.04,
        average_clv_raw=average_clv_raw,
        positive_clv_rate=1.0 if average_clv_raw is not None else None,
        attribution_count=settled_count,
        model_alpha=100.0,
        execution_drift=0.0,
        sizing_alpha=0.0,
        variance=0.0,
    )


def _ror(*, paper_only_probability: float) -> RiskOfRuinEstimate:
    hits = int(paper_only_probability * 100)
    return RiskOfRuinEstimate(
        simulations=100,
        bet_count=100,
        paper_only_hits=hits,
        halt_hits=0,
        paper_only_probability=paper_only_probability,
        halt_probability=0.0,
        worst_drawdown_pct=paper_only_probability * 100,
        median_terminal_bankroll=10_100.0,
    )
