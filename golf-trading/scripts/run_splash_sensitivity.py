"""Run a small sensitivity matrix over Splash portfolio generation."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.fantasy.splash.io_utils import (  # noqa: E402
    fixture_path as _fixture_path,
    load_json as _load_json,
    write_json as _write_json,
)
from src.storage.hashing import stable_hash  # noqa: E402

Runner = Callable[[list[str]], None]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Splash portfolio sensitivity scenarios and summarize stability."
    )
    parser.add_argument("--output-dir", default="artifacts/splash-capture/sensitivity")
    parser.add_argument(
        "--summary-output",
        default="artifacts/splash-capture/rungood-sensitivity-summary.json",
    )
    parser.add_argument("--contest-fixture", default="artifacts/splash-capture/rungood-contest-detail.json")
    parser.add_argument(
        "--player-pools-fixture",
        default="artifacts/splash-capture/rungood-player-pools-by-tier.json",
    )
    parser.add_argument(
        "--datagolf-ranks-fixture",
        default="artifacts/splash-capture/rungood-datagolf-player-ranks.json",
    )
    parser.add_argument(
        "--score-anchors-fixture",
        default="artifacts/splash-capture/rungood-datagolf-score-anchors-enriched.json",
    )
    parser.add_argument("--fantasy-projections-fixture")
    parser.add_argument("--portfolio-generator-script", default="scripts/generate_splash_portfolios.py")
    parser.add_argument("--lineup-id-prefix", default="rungood")
    parser.add_argument("--seeds", nargs="+", type=int, default=[20260701, 20260702])
    parser.add_argument("--candidate-caps", nargs="+", type=int, default=[250, 500])
    parser.add_argument(
        "--ownership-concentrations",
        nargs="+",
        type=float,
        default=[0.75, 1.0, 1.25],
    )
    parser.add_argument("--ownership-uncertainty-sd", type=float, default=0.25)
    parser.add_argument("--simulations", type=int, default=250)
    parser.add_argument("--evaluation-batch-size", type=int, default=50)
    parser.add_argument(
        "--candidate-generation",
        choices=("deterministic", "projected"),
        default="projected",
    )
    args = parser.parse_args()

    summary = run_sensitivity_matrix(
        output_dir=_fixture_path(PROJECT_ROOT, args.output_dir),
        summary_output=_fixture_path(PROJECT_ROOT, args.summary_output),
        contest_fixture=args.contest_fixture,
        player_pools_fixture=args.player_pools_fixture,
        datagolf_ranks_fixture=args.datagolf_ranks_fixture,
        score_anchors_fixture=args.score_anchors_fixture,
        fantasy_projections_fixture=args.fantasy_projections_fixture,
        portfolio_generator_script=args.portfolio_generator_script,
        lineup_id_prefix=args.lineup_id_prefix,
        seeds=tuple(args.seeds),
        candidate_caps=tuple(args.candidate_caps),
        ownership_concentrations=tuple(args.ownership_concentrations),
        ownership_uncertainty_sd=args.ownership_uncertainty_sd,
        simulations=args.simulations,
        evaluation_batch_size=args.evaluation_batch_size,
        candidate_generation=args.candidate_generation,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def run_sensitivity_matrix(
    *,
    output_dir: Path,
    summary_output: Path,
    contest_fixture: str,
    player_pools_fixture: str,
    datagolf_ranks_fixture: str,
    score_anchors_fixture: str,
    fantasy_projections_fixture: str | None,
    portfolio_generator_script: str,
    lineup_id_prefix: str,
    seeds: tuple[int, ...],
    candidate_caps: tuple[int, ...],
    ownership_concentrations: tuple[float, ...],
    ownership_uncertainty_sd: float,
    simulations: int,
    evaluation_batch_size: int,
    candidate_generation: str,
    runner: Runner | None = None,
) -> dict[str, Any]:
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    if evaluation_batch_size <= 0:
        raise ValueError("evaluation_batch_size must be positive")
    if not seeds or not candidate_caps or not ownership_concentrations:
        raise ValueError("seeds, candidate_caps, and ownership_concentrations must be non-empty")
    if any(cap <= 0 for cap in candidate_caps):
        raise ValueError("candidate caps must be positive")

    output_dir.mkdir(parents=True, exist_ok=True)
    runner = runner or _run_command
    scenario_records = []
    for seed in seeds:
        for candidate_cap in candidate_caps:
            for ownership_concentration in ownership_concentrations:
                output_path = output_dir / _scenario_filename(
                    seed=seed,
                    candidate_cap=candidate_cap,
                    ownership_concentration=ownership_concentration,
                )
                command = _scenario_command(
                    output_path=output_path,
                    contest_fixture=contest_fixture,
                    player_pools_fixture=player_pools_fixture,
                    datagolf_ranks_fixture=datagolf_ranks_fixture,
                    score_anchors_fixture=score_anchors_fixture,
                    fantasy_projections_fixture=fantasy_projections_fixture,
                    portfolio_generator_script=portfolio_generator_script,
                    lineup_id_prefix=lineup_id_prefix,
                    seed=seed,
                    candidate_cap=candidate_cap,
                    ownership_concentration=ownership_concentration,
                    ownership_uncertainty_sd=ownership_uncertainty_sd,
                    simulations=simulations,
                    evaluation_batch_size=evaluation_batch_size,
                    candidate_generation=candidate_generation,
                )
                runner(command)
                artifact = _load_json(output_path)
                scenario_records.append(
                    _scenario_record(
                        artifact,
                        output_path=output_path,
                        seed=seed,
                        candidate_cap=candidate_cap,
                        ownership_concentration=ownership_concentration,
                    )
                )

    summary = {
        "policy": (
            "Sensitivity matrix over simulation seed, candidate cap, and opponent "
            "ownership concentration. This is an audit/stability check; it does not "
            "change the underlying score model or risk gates."
        ),
        "parameters": {
            "contest_fixture": contest_fixture,
            "player_pools_fixture": player_pools_fixture,
            "datagolf_ranks_fixture": datagolf_ranks_fixture,
            "score_anchors_fixture": score_anchors_fixture,
            "fantasy_projections_fixture": fantasy_projections_fixture,
            "portfolio_generator_script": portfolio_generator_script,
            "lineup_id_prefix": lineup_id_prefix,
            "seeds": seeds,
            "candidate_caps": candidate_caps,
            "ownership_concentrations": ownership_concentrations,
            "ownership_uncertainty_sd": ownership_uncertainty_sd,
            "simulations": simulations,
            "evaluation_batch_size": evaluation_batch_size,
            "candidate_generation": candidate_generation,
        },
        "scenario_count": len(scenario_records),
        "scenarios": scenario_records,
        "stability": _stability_summary(scenario_records),
    }
    summary["artifact_hash"] = stable_hash(summary)
    _write_json(summary_output, summary)
    return summary


def _scenario_command(
    *,
    output_path: Path,
    contest_fixture: str,
    player_pools_fixture: str,
    datagolf_ranks_fixture: str,
    score_anchors_fixture: str,
    fantasy_projections_fixture: str | None,
    portfolio_generator_script: str,
    lineup_id_prefix: str,
    seed: int,
    candidate_cap: int,
    ownership_concentration: float,
    ownership_uncertainty_sd: float,
    simulations: int,
    evaluation_batch_size: int,
    candidate_generation: str,
) -> list[str]:
    command = [
        sys.executable,
        portfolio_generator_script,
        "--contest-fixture",
        contest_fixture,
        "--player-pools-fixture",
        player_pools_fixture,
        "--datagolf-ranks-fixture",
        datagolf_ranks_fixture,
        "--score-anchors-fixture",
        score_anchors_fixture,
    ]
    if fantasy_projections_fixture:
        command.extend(["--fantasy-projections-fixture", fantasy_projections_fixture])
    command.extend(
        [
        "--output",
        _path_for_command(output_path),
        "--simulations",
        str(simulations),
        "--max-candidates",
        str(candidate_cap),
        "--evaluation-batch-size",
        str(evaluation_batch_size),
        "--seed",
        str(seed),
            "--candidate-generation",
            candidate_generation,
            "--lineup-id-prefix",
            lineup_id_prefix,
            "--ownership-concentration",
        str(ownership_concentration),
        "--ownership-uncertainty-sd",
        str(ownership_uncertainty_sd),
        ]
    )
    return command


def _scenario_record(
    artifact: dict[str, Any],
    *,
    output_path: Path,
    seed: int,
    candidate_cap: int,
    ownership_concentration: float,
) -> dict[str, Any]:
    return {
        "seed": seed,
        "candidate_cap": candidate_cap,
        "ownership_concentration": ownership_concentration,
        "output_path": _path_for_command(output_path),
        "artifact_hash": artifact.get("artifact_hash"),
        "status": artifact.get("status"),
        "reports": {
            portfolio_name: _report_summary(report)
            for portfolio_name, report in artifact.get("reports", {}).items()
        },
    }


def _report_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "recommendation": report.get("recommendation"),
        "no_play_reasons": report.get("no_play_reasons", []),
        "recommended_entries": report.get("recommended_entries", 0),
        "portfolio_ev_cents": report.get("portfolio_ev_cents", 0.0),
        "ev_to_sd_ratio": report.get("ev_to_sd_ratio"),
        "manual_lineups": [
            {
                "entry_number": lineup.get("entry_number"),
                "lineup_id": lineup.get("lineup_id"),
                "players": lineup.get("players", []),
                "expected_profit_cents": lineup.get("expected_profit_cents"),
            }
            for lineup in report.get("manual_lineups", [])
        ],
    }


def _stability_summary(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    portfolio_names = sorted(
        {
            portfolio_name
            for scenario in scenarios
            for portfolio_name in scenario["reports"]
        }
    )
    return {
        portfolio_name: _portfolio_stability(scenarios, portfolio_name)
        for portfolio_name in portfolio_names
    }


def _portfolio_stability(
    scenarios: list[dict[str, Any]],
    portfolio_name: str,
) -> dict[str, Any]:
    reports = [
        scenario["reports"][portfolio_name]
        for scenario in scenarios
        if portfolio_name in scenario["reports"]
    ]
    ev_to_sd_values = [
        report["ev_to_sd_ratio"]
        for report in reports
        if report.get("ev_to_sd_ratio") is not None
    ]
    lineup_counter: Counter[tuple[str, ...]] = Counter()
    for report in reports:
        for lineup in report["manual_lineups"]:
            lineup_counter[tuple(lineup["players"])] += 1
    most_common_lineups = [
        {"players": list(players), "scenario_count": count}
        for players, count in lineup_counter.most_common(10)
    ]
    play_count = sum(1 for report in reports if report.get("recommendation") == "play")
    return {
        "scenario_count": len(reports),
        "play_count": play_count,
        "play_rate": round(play_count / len(reports), 6) if reports else 0.0,
        "recommended_entries_min": min(
            (report.get("recommended_entries", 0) for report in reports),
            default=0,
        ),
        "recommended_entries_max": max(
            (report.get("recommended_entries", 0) for report in reports),
            default=0,
        ),
        "ev_to_sd_min": min(ev_to_sd_values) if ev_to_sd_values else None,
        "ev_to_sd_max": max(ev_to_sd_values) if ev_to_sd_values else None,
        "most_common_lineups": most_common_lineups,
    }


def _scenario_filename(
    *,
    seed: int,
    candidate_cap: int,
    ownership_concentration: float,
) -> str:
    return (
        f"seed-{seed}-cap-{candidate_cap}-ownership-"
        f"{_float_label(ownership_concentration)}.json"
    )


def _float_label(value: float) -> str:
    return str(value).replace(".", "p").replace("-", "neg")


def _path_for_command(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _run_command(command: list[str]) -> None:
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


if __name__ == "__main__":
    main()
