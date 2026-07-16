"""Generate conservative and convex Splash portfolios from Splash contest fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.fantasy.splash import (  # noqa: E402
    build_splash_fantasy_report,
    datagolf_score_anchor_from_row,
    evaluate_lineup_candidates,
    fantasy_report_config,
    generate_projected_tier_valid_lineups,
    generate_tier_valid_lineups,
    optimize_lineup_portfolio,
    parse_contest_detail,
    parse_contest_player_pool,
    portfolio_config,
    simulate_player_score_distributions,
    splash_scoring_config_from_rules,
)
from src.fantasy.splash.io_utils import (  # noqa: E402
    fixture_path as _fixture_path,
    load_json as _load_json,
)
from src.fantasy.splash.models import (  # noqa: E402
    SplashLineupPortfolio,
    SplashOpponentLineupAssumptions,
)
from src.fantasy.splash.series import ContestSeriesConfig, get_series  # noqa: E402
from src.storage.hashing import stable_hash  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/rungood-splash-portfolios.json")
    parser.add_argument("--contest-fixture", default="docs/fixtures/splash/contest-detail.redacted.json")
    parser.add_argument(
        "--player-pools-fixture",
        default="tests/fixtures/splash/rungood-player-pools-by-tier.json",
    )
    parser.add_argument(
        "--datagolf-ranks-fixture",
        default="tests/fixtures/splash/rungood-datagolf-player-ranks.json",
    )
    parser.add_argument(
        "--score-anchors-fixture",
        default="tests/fixtures/splash/rungood-datagolf-score-anchors.json",
    )
    parser.add_argument("--fantasy-projections-fixture")
    parser.add_argument("--bankroll-cents", type=int, default=1_000_000)
    parser.add_argument("--simulations", type=int, default=1_000)
    parser.add_argument("--seed", type=int, default=20260701)
    parser.add_argument("--max-candidates", type=int, default=2_000)
    parser.add_argument("--evaluation-batch-size", type=int, default=50)
    parser.add_argument("--lineup-id-prefix", default="rungood")
    parser.add_argument("--ownership-concentration", type=float, default=1.0)
    parser.add_argument("--ownership-uncertainty-sd", type=float, default=0.25)
    parser.add_argument(
        "--candidate-generation",
        choices=("deterministic", "projected"),
        default="deterministic",
    )
    parser.add_argument("--series", default="rungood")
    parser.add_argument(
        "--acknowledge-exclusion",
        dest="acknowledged_exclusions",
        action="append",
        metavar="SPLASH_PLAYER_ID",
        help=(
            "Splash player ID to exclude from the hard-review gate. Only for "
            "players you've manually confirmed are genuinely absent from "
            "DataGolf's coverage, not a name-formatting bug. Repeatable."
        ),
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    series = get_series(args.series)
    contest_fixture = _fixture_path(root, args.contest_fixture)
    player_pools_fixture = _fixture_path(root, args.player_pools_fixture)
    datagolf_ranks_fixture = _fixture_path(root, args.datagolf_ranks_fixture)
    score_anchors_fixture = _fixture_path(root, args.score_anchors_fixture)
    fantasy_projections_fixture = (
        _fixture_path(root, args.fantasy_projections_fixture)
        if args.fantasy_projections_fixture
        else None
    )

    artifact = generate_portfolios(
        root=root,
        series=series,
        contest_fixture=contest_fixture,
        player_pools_fixture=player_pools_fixture,
        datagolf_ranks_fixture=datagolf_ranks_fixture,
        score_anchors_fixture=score_anchors_fixture,
        fantasy_projections_fixture=fantasy_projections_fixture,
        bankroll_cents=args.bankroll_cents,
        simulations=args.simulations,
        seed=args.seed,
        max_candidates=args.max_candidates,
        evaluation_batch_size=args.evaluation_batch_size,
        lineup_id_prefix=args.lineup_id_prefix,
        ownership_concentration=args.ownership_concentration,
        ownership_uncertainty_sd=args.ownership_uncertainty_sd,
        candidate_generation=args.candidate_generation,
        acknowledged_exclusions=frozenset(args.acknowledged_exclusions or ()),
    )
    output_path = write_portfolio_artifact(artifact, root / args.output)
    print(output_path)


def generate_portfolios(
    *,
    root: Path,
    series: ContestSeriesConfig,
    contest_fixture: Path,
    player_pools_fixture: Path,
    datagolf_ranks_fixture: Path,
    score_anchors_fixture: Path,
    fantasy_projections_fixture: Path | None,
    bankroll_cents: int,
    simulations: int,
    seed: int,
    max_candidates: int,
    evaluation_batch_size: int,
    lineup_id_prefix: str,
    ownership_concentration: float,
    ownership_uncertainty_sd: float,
    candidate_generation: str,
    acknowledged_exclusions: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    contest = parse_contest_detail(_load_json(contest_fixture))
    player_pool = parse_contest_player_pool(
        contest,
        _load_json(player_pools_fixture),
        _load_json(datagolf_ranks_fixture),
    )
    anchors = tuple(
        datagolf_score_anchor_from_row(row)
        for row in _load_json(score_anchors_fixture)
    )

    eligible_mappings = _eligible_mappings(player_pool, anchors)
    external_ownership_by_player_id = _external_ownership_by_player_id(
        player_pool,
        _load_json(fantasy_projections_fixture) if fantasy_projections_fixture else None,
    )
    players_by_tier = _eligible_players_by_tier(player_pool, eligible_mappings)
    exclusion_summary = _ineligible_player_summary(player_pool, eligible_mappings)
    hard_review_items = _hard_review_items(player_pool, anchors, acknowledged_exclusions)
    max_entries = min(series.max_entries_cap, contest.max_entries_per_user or series.max_entries_cap)
    conservative_config = portfolio_config(
        portfolio_name="conservative",
        max_entries=max_entries,
        bankroll_cents=bankroll_cents,
        minimum_marginal_ev_cents=series.conservative.minimum_marginal_ev_cents,
        max_golfer_exposure_count=series.conservative.max_golfer_exposure_count,
        max_shared_players_between_lineups=series.conservative.max_shared_players_between_lineups,
    )
    convex_config = portfolio_config(
        portfolio_name="convex",
        max_entries=max_entries,
        bankroll_cents=bankroll_cents,
        minimum_marginal_ev_cents=series.convex.minimum_marginal_ev_cents,
        max_golfer_exposure_count=series.convex.max_golfer_exposure_count,
        max_shared_players_between_lineups=series.convex.max_shared_players_between_lineups,
    )

    if hard_review_items:
        conservative = optimize_lineup_portfolio(
            candidates=(),
            config=conservative_config,
            hard_review_items=tuple(hard_review_items),
        )
        convex = optimize_lineup_portfolio(
            candidates=(),
            config=convex_config,
            hard_review_items=tuple(hard_review_items),
        )
        status = "blocked_hard_review"
    else:
        tier_requirements = {
            tier.tier_id: contest.roster_rule.number_per_tier
            for tier in player_pool.tiers
        }
        scoring_config = splash_scoring_config_from_rules()
        distributions = simulate_player_score_distributions(
            eligible_mappings,
            anchors,
            scoring_config,
            simulations=simulations,
            seed=seed,
        )
        outcomes = {
            distribution.splash_player_id: distribution.score_samples
            for distribution in distributions
        }
        if candidate_generation == "projected":
            lineups = generate_projected_tier_valid_lineups(
                players_by_tier=players_by_tier,
                tier_requirements=tier_requirements,
                sampled_golfer_outcomes=outcomes,
                drop_worst_count=contest.roster_rule.drop_worst_count,
                entry_fee_cents=contest.entry_fee_cents,
                lineup_id_prefix=lineup_id_prefix,
                max_candidates=max_candidates,
            )
        else:
            lineups = generate_tier_valid_lineups(
                players_by_tier=players_by_tier,
                tier_requirements=tier_requirements,
                entry_fee_cents=contest.entry_fee_cents,
                lineup_id_prefix=lineup_id_prefix,
                max_candidates=max_candidates,
            )
        opponent_assumptions = SplashOpponentLineupAssumptions(
            public_contest_size=contest.max_entries or len(lineups),
            seed=seed,
            external_ownership_by_player_id=external_ownership_by_player_id,
            ownership_concentration=ownership_concentration,
            ownership_uncertainty_sd=ownership_uncertainty_sd,
        )
        conservative_candidates = evaluate_lineup_candidates(
            candidate_lineups=lineups,
            players_by_tier=players_by_tier,
            tier_requirements=tier_requirements,
            sampled_golfer_outcomes=outcomes,
            drop_worst_count=contest.roster_rule.drop_worst_count,
            scoring_rules=contest.scoring_rules,
            payout_ladder=contest.payout_ladder,
            opponent_assumptions=opponent_assumptions,
            portfolio_config=conservative_config,
            evaluation_batch_size=evaluation_batch_size,
        )
        convex_candidates = evaluate_lineup_candidates(
            candidate_lineups=lineups,
            players_by_tier=players_by_tier,
            tier_requirements=tier_requirements,
            sampled_golfer_outcomes=outcomes,
            drop_worst_count=contest.roster_rule.drop_worst_count,
            scoring_rules=contest.scoring_rules,
            payout_ladder=contest.payout_ladder,
            opponent_assumptions=opponent_assumptions,
            portfolio_config=convex_config,
            evaluation_batch_size=evaluation_batch_size,
        )
        conservative = optimize_lineup_portfolio(
            candidates=conservative_candidates,
            config=conservative_config,
        )
        convex = optimize_lineup_portfolio(candidates=convex_candidates, config=convex_config)
        status = "generated"

    player_names = {
        player.splash_player_id: player.name
        for tier in player_pool.tiers
        for player in tier.players
    }
    report_config = fantasy_report_config(
        bankroll_cents=bankroll_cents,
        half_kelly_fraction=series.report.half_kelly_fraction,
        minimum_portfolio_ev_cents=series.report.minimum_portfolio_ev_cents,
        minimum_ev_to_sd_ratio=series.report.minimum_ev_to_sd_ratio,
        max_ror_probability=series.report.max_ror_probability,
        ror_simulations=series.report.ror_simulations,
        ror_seed=seed,
    )
    conservative_report = build_splash_fantasy_report(
        portfolio=conservative,
        player_names=player_names,
        config=report_config,
    )
    convex_report = build_splash_fantasy_report(
        portfolio=convex,
        player_names=player_names,
        config=report_config,
    )
    artifact = {
        "status": status,
        "contest": {
            "name": contest.name,
            "entry_fee_cents": contest.entry_fee_cents,
            "max_entries": contest.max_entries,
            "max_entries_per_user": contest.max_entries_per_user,
            "filled_entries": contest.filled_entries,
            "inputs_hash": contest.inputs_hash,
        },
        "input_fixtures": {
            "contest": _resolve_relative_path(root, contest_fixture),
            "player_pools": _resolve_relative_path(root, player_pools_fixture),
            "datagolf_ranks": _resolve_relative_path(root, datagolf_ranks_fixture),
            "score_anchors": _resolve_relative_path(root, score_anchors_fixture),
            "fantasy_projections": _resolve_relative_path(root, fantasy_projections_fixture)
            if fantasy_projections_fixture
            else None,
        },
        "local_data_summary": {
            "tier_count": len(player_pool.tiers),
            "players_by_tier": {
                str(tier.tier_id): len(tier.players)
                for tier in player_pool.tiers
            },
            "eligible_players_by_tier": {
                str(tier_id): len(players)
                for tier_id, players in sorted(players_by_tier.items())
            },
            "ineligible_players": exclusion_summary,
            "mapped_player_count": len(player_pool.player_mappings),
            "score_anchor_count": len(anchors),
            "candidate_cap": max_candidates,
            "candidate_generation": candidate_generation,
            "lineup_id_prefix": lineup_id_prefix,
            "evaluation_batch_size": evaluation_batch_size,
            "ownership_concentration": ownership_concentration,
            "ownership_uncertainty_sd": ownership_uncertainty_sd,
            "external_ownership_player_count": len(external_ownership_by_player_id),
        },
        "hard_review_items": hard_review_items,
        "portfolios": {
            "conservative": _portfolio_record(conservative, player_names),
            "convex": _portfolio_record(convex, player_names),
        },
        "reports": {
            "conservative": _report_record(conservative_report),
            "convex": _report_record(convex_report),
        },
    }
    artifact["artifact_hash"] = stable_hash(artifact)
    return artifact


def write_portfolio_artifact(artifact: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(_jsonable(artifact), indent=2, sort_keys=True) + "\n")
    return output_path


def _resolve_relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _hard_review_items(
    player_pool, anchors, acknowledged_exclusions: frozenset[str] = frozenset()
) -> list[str]:
    items = [
        f"unresolved_mapping:{item.splash_player_name}:{item.reason}"
        for item in player_pool.review_items
        if item.reason != "missing_splash_datagolf_rank"
        and item.splash_player_id not in acknowledged_exclusions
    ]
    anchored_splash_ids = {
        mapping.splash_player_id
        for mapping in player_pool.player_mappings
        if mapping.datagolf_player_id in {anchor.datagolf_player_id for anchor in anchors}
    }
    for tier in player_pool.tiers:
        anchored_players = [
            player for player in tier.players if player.splash_player_id in anchored_splash_ids
        ]
        if len(anchored_players) < tier.number_per_tier:
            items.append(
                f"tier_{tier.tier_id}_has_{len(anchored_players)}_anchored_players_"
                f"for_{tier.number_per_tier}_required"
            )
    return sorted(items)


def _external_ownership_by_player_id(
    player_pool,
    fantasy_projections: dict[str, Any] | None,
) -> dict[str, float]:
    if fantasy_projections is None:
        return {}
    projected_ownership_by_dg_id = {
        str(row["dg_id"]): float(row["proj_ownership"])
        for row in fantasy_projections.get("projections", [])
        if row.get("dg_id") is not None and row.get("proj_ownership") is not None
    }
    return {
        mapping.splash_player_id: projected_ownership_by_dg_id[mapping.datagolf_player_id]
        for mapping in player_pool.player_mappings
        if mapping.datagolf_player_id in projected_ownership_by_dg_id
    }


def _eligible_mappings(player_pool, anchors) -> tuple:
    anchor_ids = {anchor.datagolf_player_id for anchor in anchors}
    return tuple(
        mapping
        for mapping in player_pool.player_mappings
        if mapping.datagolf_player_id in anchor_ids
    )


def _eligible_players_by_tier(player_pool, eligible_mappings) -> dict[int, tuple]:
    eligible_splash_ids = {mapping.splash_player_id for mapping in eligible_mappings}
    return {
        tier.tier_id: tuple(
            player
            for player in tier.players
            if player.datagolf_rank is not None and player.datagolf_rank > 0
            and player.splash_player_id in eligible_splash_ids
        )
        for tier in player_pool.tiers
    }


def _ineligible_player_summary(player_pool, eligible_mappings) -> dict[str, Any]:
    eligible_splash_ids = {mapping.splash_player_id for mapping in eligible_mappings}
    mapped_splash_ids = {mapping.splash_player_id for mapping in player_pool.player_mappings}
    missing_rank_by_tier = {
        str(tier.tier_id): [
            player.name
            for player in tier.players
            if player.datagolf_rank is None or player.datagolf_rank <= 0
        ]
        for tier in player_pool.tiers
    }
    missing_anchor_by_tier = {
        str(tier.tier_id): [
            player.name
            for player in tier.players
            if player.splash_player_id in mapped_splash_ids
            and player.splash_player_id not in eligible_splash_ids
        ]
        for tier in player_pool.tiers
    }
    return {
        "policy": (
            "players_missing_positive_splash_datagolf_rank_or_score_anchor_are_"
            "excluded_as_insufficient_data"
        ),
        "missing_datagolf_rank_by_tier": {
            tier_id: names
            for tier_id, names in missing_rank_by_tier.items()
            if names
        },
        "missing_datagolf_rank_count": sum(
            len(names) for names in missing_rank_by_tier.values()
        ),
        "missing_score_anchor_by_tier": {
            tier_id: names
            for tier_id, names in missing_anchor_by_tier.items()
            if names
        },
        "missing_score_anchor_count": sum(
            len(names) for names in missing_anchor_by_tier.values()
        ),
    }


def _portfolio_record(
    portfolio: SplashLineupPortfolio,
    player_names: dict[str, str],
) -> dict[str, Any]:
    return {
        "portfolio_name": portfolio.portfolio_name,
        "lineup_count": len(portfolio.entries),
        "total_entry_fee_cents": portfolio.total_entry_fee_cents,
        "expected_payout_cents": portfolio.expected_payout_cents,
        "expected_profit_cents": portfolio.expected_profit_cents,
        "expected_roi": portfolio.expected_roi,
        "expected_log_growth": portfolio.expected_log_growth,
        "half_kelly_adjusted_ev_cents": portfolio.half_kelly_adjusted_ev_cents,
        "golfer_exposures": {
            player_names.get(player_id, player_id): count
            for player_id, count in sorted(portfolio.golfer_exposures.items())
        },
        "assumption_log": portfolio.assumption_log,
        "hard_review_items": portfolio.hard_review_items,
        "inputs_hash": portfolio.inputs_hash,
        "lineups": [
            {
                "rank": entry.rank,
                "lineup_id": entry.lineup.lineup_id,
                "players": [
                    {
                        "splash_player_id": player_id,
                        "name": player_names.get(player_id, player_id),
                    }
                    for player_id in entry.lineup.player_ids
                ],
                "expected_payout_cents": entry.candidate.simulation_result.expected_payout_cents,
                "expected_profit_cents": entry.candidate.expected_profit_cents,
                "half_kelly_adjusted_ev_cents": entry.candidate.half_kelly_adjusted_ev_cents,
                "expected_log_growth": entry.candidate.expected_log_growth,
                "target_duplication_count": entry.candidate.target_duplication_count,
            }
            for entry in portfolio.entries
        ],
    }


def _report_record(report) -> dict[str, Any]:
    return {
        "portfolio_name": report.portfolio_name,
        "recommendation": report.recommendation,
        "no_play_reasons": report.no_play_reasons,
        "recommended_entries": report.recommended_entries,
        "total_stake_cents": report.total_stake_cents,
        "half_kelly_fraction_used": report.half_kelly_fraction_used,
        "marginal_ev_by_lineup_cents": report.marginal_ev_by_lineup_cents,
        "portfolio_ev_cents": report.portfolio_ev_cents,
        "portfolio_variance_cents": report.portfolio_variance_cents,
        "portfolio_sd_cents": report.portfolio_sd_cents,
        "ev_to_sd_ratio": report.ev_to_sd_ratio,
        "ror_estimate": report.ror_estimate,
        "manual_lineups": [
            {
                "entry_number": lineup.entry_number,
                "lineup_id": lineup.lineup_id,
                "players": list(lineup.player_names),
                "player_ids": list(lineup.player_ids),
                "marginal_ev_cents": lineup.marginal_ev_cents,
                "expected_profit_cents": lineup.expected_profit_cents,
            }
            for lineup in report.manual_lineups
        ],
        "assumption_log": report.assumption_log,
        "inputs_hash": report.inputs_hash,
    }


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


if __name__ == "__main__":
    main()
