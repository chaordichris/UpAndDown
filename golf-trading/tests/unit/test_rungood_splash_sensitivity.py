from __future__ import annotations

import json
from pathlib import Path

from scripts.run_rungood_splash_sensitivity import run_sensitivity_matrix


def test_run_sensitivity_matrix_writes_child_artifacts_and_summary(tmp_path) -> None:
    calls: list[list[str]] = []

    def fake_runner(command: list[str]) -> None:
        calls.append(command)
        output_path = Path(command[command.index("--output") + 1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        seed = int(command[command.index("--seed") + 1])
        candidate_cap = int(command[command.index("--max-candidates") + 1])
        ownership = float(command[command.index("--ownership-concentration") + 1])
        output_path.write_text(
            json.dumps(
                _artifact(
                    recommendation="play" if ownership <= 1.0 else "no play",
                    seed=seed,
                    candidate_cap=candidate_cap,
                    ownership=ownership,
                )
            )
            + "\n"
        )

    summary = run_sensitivity_matrix(
        output_dir=tmp_path / "runs",
        summary_output=tmp_path / "summary.json",
        contest_fixture="contest.json",
        player_pools_fixture="pools.json",
        datagolf_ranks_fixture="ranks.json",
        score_anchors_fixture="anchors.json",
        fantasy_projections_fixture="fantasy.json",
        portfolio_generator_script="scripts/generate_splash_portfolios.py",
        lineup_id_prefix="contest-x",
        seeds=(1,),
        candidate_caps=(50, 100),
        ownership_concentrations=(0.75, 1.25),
        ownership_uncertainty_sd=0.25,
        simulations=10,
        evaluation_batch_size=5,
        candidate_generation="projected",
        runner=fake_runner,
    )

    assert len(calls) == 4
    assert all("--fantasy-projections-fixture" in command for command in calls)
    assert all("scripts/generate_splash_portfolios.py" in command for command in calls)
    assert all(command[command.index("--lineup-id-prefix") + 1] == "contest-x" for command in calls)
    assert summary["scenario_count"] == 4
    assert summary["parameters"]["fantasy_projections_fixture"] == "fantasy.json"
    assert summary["parameters"]["portfolio_generator_script"] == "scripts/generate_splash_portfolios.py"
    assert summary["parameters"]["lineup_id_prefix"] == "contest-x"
    assert summary["parameters"]["candidate_generation"] == "projected"
    assert summary["stability"]["conservative"]["play_count"] == 2
    assert summary["stability"]["conservative"]["play_rate"] == 0.5
    assert summary["stability"]["conservative"]["recommended_entries_min"] == 0
    assert summary["stability"]["conservative"]["recommended_entries_max"] == 1
    assert summary["stability"]["conservative"]["most_common_lineups"][0] == {
        "players": ["Alpha", "Bravo"],
        "scenario_count": 4,
    }
    assert summary["artifact_hash"]
    assert (tmp_path / "summary.json").exists()


def test_run_sensitivity_matrix_requires_non_empty_dimensions(tmp_path) -> None:
    try:
        run_sensitivity_matrix(
            output_dir=tmp_path / "runs",
            summary_output=tmp_path / "summary.json",
            contest_fixture="contest.json",
            player_pools_fixture="pools.json",
            datagolf_ranks_fixture="ranks.json",
            score_anchors_fixture="anchors.json",
            fantasy_projections_fixture=None,
            portfolio_generator_script="scripts/generate_splash_portfolios.py",
            lineup_id_prefix="contest-x",
            seeds=(),
            candidate_caps=(50,),
            ownership_concentrations=(1.0,),
            ownership_uncertainty_sd=0.25,
            simulations=10,
            evaluation_batch_size=5,
            candidate_generation="projected",
            runner=lambda command: None,
        )
    except ValueError as error:
        assert "must be non-empty" in str(error)
    else:
        raise AssertionError("expected ValueError")


def _artifact(
    *,
    recommendation: str,
    seed: int,
    candidate_cap: int,
    ownership: float,
) -> dict:
    recommended_entries = 1 if recommendation == "play" else 0
    return {
        "artifact_hash": f"hash-{seed}-{candidate_cap}-{ownership}",
        "status": "generated",
        "reports": {
            "conservative": {
                "recommendation": recommendation,
                "no_play_reasons": [] if recommendation == "play" else ["sensitive"],
                "recommended_entries": recommended_entries,
                "portfolio_ev_cents": 100.0 if recommendation == "play" else 0.0,
                "ev_to_sd_ratio": 0.2 if recommendation == "play" else 0.0,
                "manual_lineups": [
                    {
                        "entry_number": 1,
                        "lineup_id": "lineup-1",
                        "players": ["Alpha", "Bravo"],
                        "expected_profit_cents": 100.0,
                    }
                ],
            }
        },
    }
