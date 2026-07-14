from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from src.fantasy.splash import (
    build_splash_fantasy_report,
    datagolf_references_from_rows,
    datagolf_score_anchor_from_row,
    fantasy_report_config,
    generate_opponent_lineup_pool,
    generate_projected_tier_valid_lineups,
    generate_tier_valid_lineups,
    lineup_from_players,
    map_players_to_datagolf,
    optimize_lineup_portfolio,
    parse_contest_detail,
    parse_contest_player_pool,
    parse_player_pool,
    payout_for_rank,
    persist_raw_snapshot,
    portfolio_candidate_from_result,
    portfolio_config,
    run_opponent_ownership_sensitivity,
    score_distributions_to_records,
    score_lineup,
    simulate_lineup_outcomes,
    simulate_lineup_with_generated_opponents,
    simulate_player_score_distributions,
    splash_scoring_config_from_rules,
)
from src.fantasy.splash.models import (
    SplashLineupSimulationResult,
    SplashOpponentLineupAssumptions,
    SplashPayout,
    SplashPlayer,
)
from src.storage.models import SplashRawSnapshot

SPLASH_FIXTURES = Path(__file__).resolve().parents[2] / "docs" / "fixtures" / "splash"
TEST_SPLASH_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "splash"


def _load_fixture(name: str, *, test_fixture: bool = False) -> dict | list[dict]:
    fixture_dir = TEST_SPLASH_FIXTURES if test_fixture else SPLASH_FIXTURES
    with open(fixture_dir / name) as fixture:
        return json.load(fixture)


def test_rungood_contest_detail_parses_expected_settings() -> None:
    contest = parse_contest_detail(_load_fixture("contest-detail.redacted.json"))

    assert contest.name == "RunGood $25K John Deere Classic - Total Strokes"
    assert contest.entry_fee_cents == 2500
    assert contest.entry_fee_dollars == 25
    assert contest.max_entries == 1112
    assert contest.max_entries_per_user == 33
    assert contest.filled_entries == 625
    assert len(contest.inputs_hash) == 64

    assert len(contest.payout_ladder) == 12
    assert contest.payout_ladder[0].label == "1st"
    assert contest.payout_ladder[0].start_rank == 1
    assert contest.payout_ladder[0].end_rank == 1
    assert contest.payout_ladder[0].amount_cents == 250200
    assert contest.payout_ladder[-1].label == "108th - 200th"
    assert contest.payout_ladder[-1].start_rank == 108
    assert contest.payout_ladder[-1].end_rank == 200
    assert contest.payout_ladder[-1].amount_cents == 5004

    scoring = {rule.description: rule.points for rule in contest.scoring_rules}
    assert scoring["-1 fantasy points for each stroke under par"] == -1
    assert scoring["0 fantasy points for a par"] == 0
    assert scoring["1 fantasy point for each stroke over par"] == 1
    assert scoring["8 fantasy points for missed or incomplete rounds"] == 8
    assert scoring["Worst scoring golfer does not count towards the score"] is None

    assert contest.roster_rule.expected_picks_count == 6
    assert contest.roster_rule.number_of_tiers == 6
    assert contest.roster_rule.number_per_tier == 1
    assert contest.roster_rule.drop_worst_count == 1
    assert contest.roster_rule.metric_name == "datagolf_rank"
    assert contest.roster_rule.score_type == "golf_score"
    assert "select 1 golfer from each of the 6 tiers" in contest.roster_rule.description

    assert len(contest.tiers) == 6
    assert {tier.tier_id for tier in contest.tiers} == {1, 2, 3, 4, 5, 6}
    assert all(tier.number_per_tier == 1 for tier in contest.tiers)

    assert len(contest.slates) == 1
    assert contest.slates[0].name == "John Deere Classic"
    assert contest.slates[0].sport == "golf"
    assert contest.slates[0].league == "pga"


def test_player_pool_parses_tier_players() -> None:
    tier = parse_player_pool(_load_fixture("player-pool-tier1.redacted.json"), tier_id=1)

    assert tier.tier_id == 1
    assert tier.max_players == 10
    assert tier.metric_name == "datagolf_rank"
    assert tier.players[0].name == "Ben Griffin"
    assert tier.players[0].datagolf_rank == 18
    assert tier.players[0].world_rank == 18
    assert tier.players[0].scoring_avg == 70.415
    assert tier.players[0].is_selectable is True
    assert len(tier.players[0].inputs_hash) == 64


def test_contest_player_pool_extracts_tiers_and_datagolf_mappings() -> None:
    contest = parse_contest_detail(_load_fixture("contest-detail.redacted.json"))
    pools_by_tier = _load_fixture("rungood-player-pools-by-tier.json", test_fixture=True)
    datagolf_rows = _load_fixture("rungood-datagolf-player-ranks.json", test_fixture=True)

    player_pool = parse_contest_player_pool(contest, pools_by_tier, datagolf_rows)

    assert player_pool.contest_id == contest.splash_id
    assert player_pool.slate_id == contest.slates[0].splash_id
    assert {tier.tier_id for tier in player_pool.tiers} == {1, 2, 3, 4, 5, 6}
    assert [player.name for player in player_pool.tiers[0].players] == [
        "Ben Griffin",
        "Chris Gotterup",
    ]
    assert player_pool.tiers[0].players[0].tier_id == 1
    assert player_pool.tiers[5].players[0].tier_id == 6

    mapping_by_name = {
        mapping.splash_player_name: mapping.datagolf_player_id
        for mapping in player_pool.player_mappings
    }
    assert mapping_by_name == {
        "Ben Griffin": "dg_ben_griffin",
        "Chris Gotterup": "dg_chris_gotterup",
        "Akshay Bhatia": "dg_akshay_bhatia",
        "Keith Mitchell": "dg_keith_mitchell",
        "J.T. Poston": "dg_jt_poston",
    }

    review_by_name = {item.splash_player_name: item.reason for item in player_pool.review_items}
    assert review_by_name == {
        "Rank Mismatch": "datagolf_rank_mismatch",
        "Unmapped Player": "no_exact_name_match",
    }
    assert len(player_pool.inputs_hash) == 64


def test_contest_player_pool_requires_all_expected_tiers() -> None:
    contest = parse_contest_detail(_load_fixture("contest-detail.redacted.json"))
    pools_by_tier = _load_fixture("rungood-player-pools-by-tier.json", test_fixture=True)
    datagolf_rows = _load_fixture("rungood-datagolf-player-ranks.json", test_fixture=True)
    pools_by_tier.pop("6")

    with pytest.raises(ValueError, match="Missing Splash player-pool payloads"):
        parse_contest_player_pool(contest, pools_by_tier, datagolf_rows)


def test_datagolf_mapping_never_silently_accepts_name_only_match() -> None:
    player = parse_player_pool(
        _load_fixture("rungood-player-pools-by-tier.json", test_fixture=True)["5"],
        tier_id=5,
    ).players[0]
    references = datagolf_references_from_rows(
        [
            {
                "player_id": "dg_rank_mismatch",
                "player_name": "Rank Mismatch",
                "datagolf_rank": 44,
            }
        ]
    )

    mappings, review_items = map_players_to_datagolf((player,), references)

    assert mappings == ()
    assert len(review_items) == 1
    assert review_items[0].reason == "datagolf_rank_mismatch"
    assert review_items[0].candidates == ("dg_rank_mismatch|Rank Mismatch|rank=44",)


def test_datagolf_mapping_requires_rank_evidence() -> None:
    with pytest.raises(KeyError, match="must include datagolf_rank"):
        datagolf_references_from_rows(
            [{"player_id": "dg_missing_rank", "player_name": "Missing Rank"}]
        )


def test_datagolf_anchored_score_model_outputs_distributions_with_provenance() -> None:
    contest = parse_contest_detail(_load_fixture("contest-detail.redacted.json"))
    pools_by_tier = _load_fixture("rungood-player-pools-by-tier.json", test_fixture=True)
    datagolf_rows = _load_fixture("rungood-datagolf-player-ranks.json", test_fixture=True)
    player_pool = parse_contest_player_pool(contest, pools_by_tier, datagolf_rows)
    mappings = tuple(player_pool.player_mappings[:2])
    anchors = tuple(
        datagolf_score_anchor_from_row(row)
        for row in _load_fixture("rungood-datagolf-score-anchors.json", test_fixture=True)
    )
    config = splash_scoring_config_from_rules(
        tournament_rounds=4,
        cut_rounds_played=2,
        missed_round_penalty_points=8.0,
        cut_probability_prior_strength=100.0,
    )

    distributions = simulate_player_score_distributions(
        mappings,
        anchors,
        config,
        simulations=500,
        seed=7,
    )
    records = score_distributions_to_records(distributions)

    assert [distribution.splash_player_name for distribution in distributions] == [
        "Ben Griffin",
        "Chris Gotterup",
    ]
    assert all(distribution.simulations == 500 for distribution in distributions)
    assert all(len(distribution.score_samples) == 500 for distribution in distributions)
    assert all(distribution.sd_score > 0.0 for distribution in distributions)
    assert all(distribution.p10_score < distribution.p50_score for distribution in distributions)
    assert all(distribution.p50_score < distribution.p90_score for distribution in distributions)
    assert distributions[0].simulated_make_cut_rate == pytest.approx(0.82, abs=0.08)
    assert distributions[0].simulated_missed_rounds_mean > 0.0
    assert all(len(distribution.inputs_hash) == 64 for distribution in distributions)
    assert records[0]["provenance"]["model_version"] == "splash-datagolf-score-v1"
    assert records[0]["provenance"]["inputs_hash"] == distributions[0].inputs_hash


def test_score_model_is_seed_reproducible() -> None:
    mappings = parse_contest_player_pool(
        parse_contest_detail(_load_fixture("contest-detail.redacted.json")),
        _load_fixture("rungood-player-pools-by-tier.json", test_fixture=True),
        _load_fixture("rungood-datagolf-player-ranks.json", test_fixture=True),
    ).player_mappings[:1]
    anchors = tuple(
        datagolf_score_anchor_from_row(row)
        for row in _load_fixture("rungood-datagolf-score-anchors.json", test_fixture=True)
    )
    config = splash_scoring_config_from_rules()

    first = simulate_player_score_distributions(
        tuple(mappings),
        anchors,
        config,
        simulations=100,
        seed=42,
    )
    second = simulate_player_score_distributions(
        tuple(mappings),
        anchors,
        config,
        simulations=100,
        seed=42,
    )

    assert first == second


def test_score_model_requires_datagolf_score_anchor_for_each_mapping() -> None:
    player_pool = parse_contest_player_pool(
        parse_contest_detail(_load_fixture("contest-detail.redacted.json")),
        _load_fixture("rungood-player-pools-by-tier.json", test_fixture=True),
        _load_fixture("rungood-datagolf-player-ranks.json", test_fixture=True),
    )
    config = splash_scoring_config_from_rules()

    with pytest.raises(ValueError, match="Missing DataGolf score anchors"):
        simulate_player_score_distributions(
            player_pool.player_mappings,
            (),
            config,
            simulations=10,
            seed=1,
        )


def test_score_anchor_requires_datagolf_score_moments() -> None:
    with pytest.raises(KeyError, match="made_cut_score_mean"):
        datagolf_score_anchor_from_row(
            {
                "player_id": "dg_missing_score",
                "player_name": "Missing Score",
                "datagolf_rank": 50,
                "make_cut_probability": 0.5,
            }
        )


@pytest.mark.parametrize(
    ("drop_worst_count", "expected_score"),
    [
        (0, 14.0),
        (1, 4.0),
        (2, 1.0),
    ],
)
def test_lineup_scoring_drops_highest_scores(drop_worst_count: int, expected_score: float) -> None:
    lineup = lineup_from_players(
        lineup_id="drop-test",
        player_ids=("p1", "p2", "p3"),
        entry_fee_cents=100,
    )
    outcomes = {
        "p1": (1.0,),
        "p2": (10.0,),
        "p3": (3.0,),
    }

    assert score_lineup(
        lineup=lineup,
        sampled_golfer_outcomes=outcomes,
        simulation_index=0,
        drop_worst_count=drop_worst_count,
    ) == expected_score


def test_lineup_scoring_refuses_dropping_entire_lineup() -> None:
    lineup = lineup_from_players(
        lineup_id="drop-all-test",
        player_ids=("p1", "p2"),
        entry_fee_cents=100,
    )

    with pytest.raises(ValueError, match="drop_worst_count must be less than lineup size"):
        score_lineup(
            lineup=lineup,
            sampled_golfer_outcomes={"p1": (1.0,), "p2": (2.0,)},
            simulation_index=0,
            drop_worst_count=2,
        )


@pytest.mark.parametrize(
    ("rank", "expected_payout"),
    [
        (1, 1000),
        (2, 500),
        (3, 500),
        (4, 0),
    ],
)
def test_payout_for_rank_handles_ranges_and_misses(rank: int, expected_payout: int) -> None:
    assert payout_for_rank(rank, _payout_ladder()) == expected_payout


def test_payout_for_rank_refuses_invalid_rank() -> None:
    with pytest.raises(ValueError, match="rank must be positive"):
        payout_for_rank(0, _payout_ladder())


def test_lineup_simulator_returns_roi_variance_and_drawdown_metrics() -> None:
    lineups = (
        lineup_from_players(lineup_id="l1", player_ids=("a", "c"), entry_fee_cents=100),
        lineup_from_players(lineup_id="l2", player_ids=("b", "d"), entry_fee_cents=100),
    )
    outcomes = {
        "a": (1.0, 10.0),
        "b": (2.0, 1.0),
        "c": (1.0, 10.0),
        "d": (2.0, 1.0),
    }

    results = simulate_lineup_outcomes(
        lineups=lineups,
        sampled_golfer_outcomes=outcomes,
        player_tiers={"a": 1, "b": 1, "c": 2, "d": 2},
        tier_requirements={1: 1, 2: 1},
        drop_worst_count=0,
        scoring_rules=(),
        payout_ladder=(SplashPayout("1st", 1, 1, 300, 0, "hash"),),
        field_size=2,
    )
    result_by_id = {result.lineup_id: result for result in results}

    assert result_by_id["l1"].expected_payout_cents == 150.0
    assert result_by_id["l1"].roi == 0.5
    assert result_by_id["l1"].cash_probability == 0.5
    assert result_by_id["l1"].top_10_probability == 1.0
    assert result_by_id["l1"].win_probability == 0.5
    assert result_by_id["l1"].profit_variance_cents == 22500.0
    assert result_by_id["l1"].drawdown_contribution_cents == 50.0
    assert len(result_by_id["l1"].inputs_hash) == 64


def test_lineup_simulator_splits_tied_payout_slots() -> None:
    lineups = (
        lineup_from_players(lineup_id="l1", player_ids=("a", "c"), entry_fee_cents=100),
        lineup_from_players(lineup_id="l2", player_ids=("b", "d"), entry_fee_cents=100),
    )
    outcomes = {
        "a": (1.0,),
        "b": (1.0,),
        "c": (1.0,),
        "d": (1.0,),
    }

    results = simulate_lineup_outcomes(
        lineups=lineups,
        sampled_golfer_outcomes=outcomes,
        player_tiers={"a": 1, "b": 1, "c": 2, "d": 2},
        tier_requirements={1: 1, 2: 1},
        drop_worst_count=0,
        scoring_rules=(),
        payout_ladder=(
            SplashPayout("1st", 1, 1, 1000, 0, "hash"),
            SplashPayout("2nd", 2, 2, 0, 1, "hash"),
        ),
        field_size=2,
    )

    assert [result.expected_payout_cents for result in results] == [500.0, 500.0]
    assert [result.win_probability for result in results] == [1.0, 1.0]


def test_lineup_simulator_enforces_tier_constraints() -> None:
    lineups = (
        lineup_from_players(lineup_id="bad", player_ids=("a", "b"), entry_fee_cents=100),
    )

    with pytest.raises(ValueError, match="violates tier requirements"):
        simulate_lineup_outcomes(
            lineups=lineups,
            sampled_golfer_outcomes={"a": (1.0,), "b": (2.0,)},
            player_tiers={"a": 1, "b": 1},
            tier_requirements={1: 1, 2: 1},
            drop_worst_count=0,
            scoring_rules=(),
            payout_ladder=_payout_ladder(),
            field_size=1,
        )


def test_splash_raw_snapshot_persists_immutable_capture_with_hash(db_session) -> None:
    capture = _load_fixture("contest-detail.redacted.json")
    response_body = capture["response_body"]

    snapshot = persist_raw_snapshot(
        db_session,
        endpoint="/contests/<public_contest_uuid>",
        method="GET",
        url=capture["url"],
        request_headers=capture["request_headers"],
        response_headers=capture["response_headers"],
        response_body=response_body,
        response_status=capture["response_status"],
        captured_at=datetime.fromisoformat(capture["captured_at"].replace("Z", "+00:00")),
    )

    fetched = db_session.get(SplashRawSnapshot, snapshot.snapshot_id)
    assert fetched is not None
    assert fetched.response_status == 200
    assert len(fetched.inputs_hash) == 64
    assert json.loads(fetched.response_body)["name"] == (
        "RunGood $25K John Deere Classic - Total Strokes"
    )

    second_snapshot = persist_raw_snapshot(
        db_session,
        endpoint="/contests/<public_contest_uuid>",
        method="GET",
        url=capture["url"],
        request_headers=capture["request_headers"],
        response_headers=capture["response_headers"],
        response_body=response_body,
        response_status=capture["response_status"],
        captured_at=datetime.fromisoformat(capture["captured_at"].replace("Z", "+00:00")),
    )

    assert second_snapshot.snapshot_id != snapshot.snapshot_id
    assert second_snapshot.inputs_hash == snapshot.inputs_hash


def test_opponent_generator_returns_tier_valid_field_with_logged_assumptions(caplog) -> None:
    players_by_tier = _opponent_players_by_tier()
    assumptions = SplashOpponentLineupAssumptions(
        public_contest_size=8,
        seed=11,
        ownership_concentration=1.5,
        ownership_uncertainty_sd=0.0,
    )

    with caplog.at_level(logging.INFO, logger="src.fantasy.splash.opponent_lineups"):
        pool = generate_opponent_lineup_pool(
            players_by_tier=players_by_tier,
            tier_requirements={1: 1, 2: 1},
            entry_fee_cents=100,
            assumptions=assumptions,
            reserved_lineup_count=1,
        )

    assert len(pool.lineups) == 7
    assert all(len(lineup.player_ids) == 2 for lineup in pool.lineups)
    assert all(lineup.player_ids[0].startswith("t1-") for lineup in pool.lineups)
    assert all(lineup.player_ids[1].startswith("t2-") for lineup in pool.lineups)
    assert pool.assumption_log["public_contest_size"] == 8
    assert pool.assumption_log["generated_opponent_count"] == 7
    assert len(pool.inputs_hash) == 64
    assert "ownership_concentration" in caplog.text


def test_opponent_generator_uses_rank_and_tier_position_to_estimate_duplication() -> None:
    players_by_tier = _opponent_players_by_tier()
    low_chalk_pool = generate_opponent_lineup_pool(
        players_by_tier=players_by_tier,
        tier_requirements={1: 1, 2: 1},
        entry_fee_cents=100,
        assumptions=SplashOpponentLineupAssumptions(
            public_contest_size=30,
            seed=3,
            ownership_concentration=0.1,
            ownership_uncertainty_sd=0.0,
        ),
    )
    high_chalk_pool = generate_opponent_lineup_pool(
        players_by_tier=players_by_tier,
        tier_requirements={1: 1, 2: 1},
        entry_fee_cents=100,
        assumptions=SplashOpponentLineupAssumptions(
            public_contest_size=30,
            seed=3,
            ownership_concentration=8.0,
            ownership_uncertainty_sd=0.0,
        ),
    )

    assert high_chalk_pool.max_duplicate_count > low_chalk_pool.max_duplicate_count
    assert high_chalk_pool.duplicated_entry_share > low_chalk_pool.duplicated_entry_share


def test_opponent_generator_uses_external_ownership_priors() -> None:
    players_by_tier = {
        1: (
            _opponent_player("rank-chalk", "Rank Chalk", tier_id=1, datagolf_rank=1),
            _opponent_player("public-chalk", "Public Chalk", tier_id=1, datagolf_rank=50),
        ),
    }

    pool = generate_opponent_lineup_pool(
        players_by_tier=players_by_tier,
        tier_requirements={1: 1},
        entry_fee_cents=100,
        assumptions=SplashOpponentLineupAssumptions(
            public_contest_size=100,
            seed=4,
            datagolf_rank_weight=0.0,
            tier_position_weight=0.0,
            external_ownership_by_player_id={"rank-chalk": 1.0, "public-chalk": 99.0},
            ownership_concentration=1.0,
            ownership_uncertainty_sd=0.0,
        ),
    )
    selected_counts = Counter(lineup.player_ids[0] for lineup in pool.lineups)

    assert selected_counts["public-chalk"] > selected_counts["rank-chalk"]
    assert pool.assumption_log["external_ownership_player_count"] == 2
    assert pool.assumption_log["external_ownership_inputs_hash"]


def test_generated_opponents_flow_into_split_payout_estimates() -> None:
    players_by_tier = {
        1: (_opponent_player("t1-a", "Tier 1 Chalk", tier_id=1, datagolf_rank=1),),
        2: (_opponent_player("t2-a", "Tier 2 Chalk", tier_id=2, datagolf_rank=2),),
    }
    target = lineup_from_players(
        lineup_id="target",
        player_ids=("t1-a", "t2-a"),
        entry_fee_cents=100,
    )

    result = simulate_lineup_with_generated_opponents(
        target_lineups=(target,),
        players_by_tier=players_by_tier,
        tier_requirements={1: 1, 2: 1},
        sampled_golfer_outcomes={"t1-a": (1.0,), "t2-a": (1.0,)},
        drop_worst_count=0,
        scoring_rules=(),
        payout_ladder=(SplashPayout("1st", 1, 1, 900, 0, "hash"),),
        assumptions=SplashOpponentLineupAssumptions(
            public_contest_size=3,
            seed=99,
            ownership_concentration=1.0,
            ownership_uncertainty_sd=0.0,
        ),
    )

    assert result.target_duplication_counts == {"target": 3}
    assert result.target_results[0].expected_payout_cents == 300.0
    assert result.target_results[0].roi == 2.0
    assert result.opponent_pool.max_duplicate_count == 2


def test_ownership_sensitivity_flags_lineups_dependent_on_ownership_guesses() -> None:
    players_by_tier = _opponent_players_by_tier()
    target = lineup_from_players(
        lineup_id="target-chalk",
        player_ids=("t1-a", "t2-a"),
        entry_fee_cents=100,
    )

    report = run_opponent_ownership_sensitivity(
        target_lineups=(target,),
        players_by_tier=players_by_tier,
        tier_requirements={1: 1, 2: 1},
        sampled_golfer_outcomes={
            "t1-a": (1.0,),
            "t1-b": (5.0,),
            "t2-a": (1.0,),
            "t2-b": (5.0,),
        },
        drop_worst_count=0,
        scoring_rules=(),
        payout_ladder=(SplashPayout("1st", 1, 1, 1000, 0, "hash"),),
        assumptions=SplashOpponentLineupAssumptions(
            public_contest_size=8,
            seed=21,
            ownership_concentration=1.0,
            ownership_uncertainty_sd=0.0,
            sensitivity_concentration_multipliers=(0.1, 10.0),
            sensitivity_roi_threshold=0.01,
        ),
    )

    assert [scenario.label for scenario in report.scenarios] == ["0.1x", "10x"]
    assert report.ev_dependency_flags == {"target-chalk": True}
    assert report.roi_range_by_lineup["target-chalk"] > 0.01
    assert len(report.inputs_hash) == 64


def test_opponent_generator_requires_datagolf_rank_for_ownership() -> None:
    players_by_tier = {
        1: (_opponent_player("missing-rank", "Missing Rank", tier_id=1, datagolf_rank=None),),
    }

    with pytest.raises(ValueError, match="missing a positive DataGolf rank"):
        generate_opponent_lineup_pool(
            players_by_tier=players_by_tier,
            tier_requirements={1: 1},
            entry_fee_cents=100,
            assumptions=SplashOpponentLineupAssumptions(public_contest_size=1, seed=1),
        )


def test_portfolio_optimizer_selects_entries_with_exposure_and_correlation_caps() -> None:
    config = portfolio_config(
        portfolio_name="conservative",
        max_entries=3,
        bankroll_cents=10_000,
        minimum_marginal_ev_cents=0.0,
        max_golfer_exposure_count=2,
        max_shared_players_between_lineups=1,
    )
    candidates = (
        _portfolio_candidate("l1", ("a", "c"), expected_payout=140, variance=100, config=config),
        _portfolio_candidate("l2", ("a", "d"), expected_payout=130, variance=100, config=config),
        _portfolio_candidate("l3", ("b", "c"), expected_payout=125, variance=100, config=config),
        _portfolio_candidate("too-correlated", ("a", "c"), expected_payout=120, variance=100, config=config),
        _portfolio_candidate("below-ev", ("b", "d"), expected_payout=90, variance=100, config=config),
    )

    portfolio = optimize_lineup_portfolio(candidates=candidates, config=config)

    assert [entry.lineup.lineup_id for entry in portfolio.entries] == ["l1", "l2", "l3"]
    assert portfolio.golfer_exposures == {"a": 2, "c": 2, "d": 1, "b": 1}
    assert portfolio.total_entry_fee_cents == 300
    assert portfolio.expected_profit_cents == 95.0
    assert portfolio.expected_roi == pytest.approx(0.316667)
    assert len(portfolio.inputs_hash) == 64


def test_portfolio_optimizer_blocks_lineups_below_minimum_marginal_adjusted_ev() -> None:
    config = portfolio_config(
        portfolio_name="convex",
        max_entries=2,
        bankroll_cents=1_000,
        minimum_marginal_ev_cents=20.0,
        max_golfer_exposure_count=2,
        max_shared_players_between_lineups=2,
    )
    candidates = (
        _portfolio_candidate("thin", ("a", "c"), expected_payout=115, variance=10_000, config=config),
        _portfolio_candidate("good", ("b", "d"), expected_payout=150, variance=100, config=config),
    )

    portfolio = optimize_lineup_portfolio(candidates=candidates, config=config)

    assert [entry.lineup.lineup_id for entry in portfolio.entries] == ["good"]
    assert portfolio.entries[0].marginal_adjusted_ev_cents > 20.0


def test_generate_tier_valid_lineups_enumerates_tier_combinations() -> None:
    lineups = generate_tier_valid_lineups(
        players_by_tier=_opponent_players_by_tier(),
        tier_requirements={1: 1, 2: 1},
        entry_fee_cents=100,
        lineup_id_prefix="run",
    )

    assert [lineup.player_ids for lineup in lineups] == [
        ("t1-a", "t2-a"),
        ("t1-a", "t2-b"),
        ("t1-b", "t2-a"),
        ("t1-b", "t2-b"),
    ]


def test_generate_projected_tier_valid_lineups_keeps_best_projected_candidates() -> None:
    lineups = generate_projected_tier_valid_lineups(
        players_by_tier=_opponent_players_by_tier(),
        tier_requirements={1: 1, 2: 1},
        sampled_golfer_outcomes={
            "t1-a": (10.0, 12.0),
            "t1-b": (1.0, 3.0),
            "t2-a": (8.0, 10.0),
            "t2-b": (2.0, 4.0),
        },
        drop_worst_count=0,
        entry_fee_cents=100,
        lineup_id_prefix="projected",
        max_candidates=1,
    )

    assert [lineup.lineup_id for lineup in lineups] == ["projected-1"]
    assert [lineup.player_ids for lineup in lineups] == [("t1-b", "t2-b")]


def test_generate_projected_tier_valid_lineups_applies_drop_worst_projection() -> None:
    lineups = generate_projected_tier_valid_lineups(
        players_by_tier={
            1: (
                _opponent_player("t1-a", "Tier 1 Steady", tier_id=1, datagolf_rank=1),
                _opponent_player("t1-b", "Tier 1 Volatile", tier_id=1, datagolf_rank=2),
            ),
            2: (_opponent_player("t2-a", "Tier 2 Best", tier_id=2, datagolf_rank=3),),
            3: (_opponent_player("t3-a", "Tier 3 Worst", tier_id=3, datagolf_rank=4),),
        },
        tier_requirements={1: 1, 2: 1, 3: 1},
        sampled_golfer_outcomes={
            "t1-a": (2.0,),
            "t1-b": (10.0,),
            "t2-a": (1.0,),
            "t3-a": (11.0,),
        },
        drop_worst_count=1,
        entry_fee_cents=100,
        max_candidates=1,
    )

    assert [lineup.player_ids for lineup in lineups] == [("t1-a", "t2-a", "t3-a")]


def test_generate_projected_tier_valid_lineups_requires_sampled_outcomes() -> None:
    with pytest.raises(ValueError, match="Missing sampled outcomes"):
        generate_projected_tier_valid_lineups(
            players_by_tier=_opponent_players_by_tier(),
            tier_requirements={1: 1, 2: 1},
            sampled_golfer_outcomes={
                "t1-a": (10.0,),
                "t1-b": (1.0,),
                "t2-a": (8.0,),
            },
            drop_worst_count=0,
            entry_fee_cents=100,
            max_candidates=1,
        )


def test_splash_fantasy_report_recommends_entries_and_exact_manual_lineups() -> None:
    config = portfolio_config(
        portfolio_name="conservative",
        max_entries=2,
        bankroll_cents=10_000,
        minimum_marginal_ev_cents=0.0,
        max_golfer_exposure_count=2,
        max_shared_players_between_lineups=1,
    )
    portfolio = optimize_lineup_portfolio(
        candidates=(
            _portfolio_candidate("l1", ("a", "c"), expected_payout=160, variance=100, config=config),
            _portfolio_candidate("l2", ("b", "d"), expected_payout=150, variance=400, config=config),
        ),
        config=config,
    )

    report = build_splash_fantasy_report(
        portfolio=portfolio,
        player_names={"a": "Alpha", "b": "Bravo", "c": "Charlie", "d": "Delta"},
        config=fantasy_report_config(
            bankroll_cents=10_000,
            half_kelly_fraction=0.5,
            minimum_ev_to_sd_ratio=0.01,
            max_ror_probability=1.0,
            ror_simulations=100,
            ror_seed=7,
        ),
    )

    assert report.recommendation == "play"
    assert report.recommended_entries == 2
    assert report.total_stake_cents == 200
    assert report.half_kelly_fraction_used == 0.5
    assert report.portfolio_ev_cents == 110.0
    assert report.portfolio_variance_cents == 500
    assert report.portfolio_sd_cents == pytest.approx(22.3607)
    assert report.ror_estimate["method"] == "single_portfolio_normal_return_monte_carlo"
    assert report.marginal_ev_by_lineup_cents == (
        ("l1", pytest.approx(59.9975)),
        ("l2", pytest.approx(49.99)),
    )
    assert [lineup.player_names for lineup in report.manual_lineups] == [
        ("Alpha", "Charlie"),
        ("Bravo", "Delta"),
    ]
    assert len(report.inputs_hash) == 64


def test_splash_fantasy_report_says_no_play_for_negative_or_uncertain_edge() -> None:
    config = portfolio_config(
        portfolio_name="convex",
        max_entries=2,
        bankroll_cents=10_000,
        minimum_marginal_ev_cents=0.0,
        max_golfer_exposure_count=2,
        max_shared_players_between_lineups=1,
    )
    portfolio = optimize_lineup_portfolio(
        candidates=(),
        config=config,
        hard_review_items=("missing_datagolf_score_anchors:Example Player",),
    )

    report = build_splash_fantasy_report(
        portfolio=portfolio,
        player_names={},
        config=fantasy_report_config(
            bankroll_cents=10_000,
            half_kelly_fraction=0.5,
            minimum_portfolio_ev_cents=0.0,
            ror_simulations=100,
        ),
    )

    assert report.recommendation == "no play"
    assert report.recommended_entries == 0
    assert report.total_stake_cents == 0
    assert "too_uncertain:hard_review_items_present" in report.no_play_reasons
    assert "negative_or_insufficient_edge" in report.no_play_reasons
    assert report.ror_estimate["method"] == "not_applicable_no_entries"


def _payout_ladder() -> tuple[SplashPayout, ...]:
    return (
        SplashPayout("1st", 1, 1, 1000, 0, "hash"),
        SplashPayout("2nd - 3rd", 2, 3, 500, 1, "hash"),
    )


def _opponent_players_by_tier() -> dict[int, tuple[SplashPlayer, ...]]:
    return {
        1: (
            _opponent_player("t1-a", "Tier 1 Chalk", tier_id=1, datagolf_rank=1),
            _opponent_player("t1-b", "Tier 1 Pivot", tier_id=1, datagolf_rank=50),
        ),
        2: (
            _opponent_player("t2-a", "Tier 2 Chalk", tier_id=2, datagolf_rank=2),
            _opponent_player("t2-b", "Tier 2 Pivot", tier_id=2, datagolf_rank=60),
        ),
    }


def _opponent_player(
    splash_player_id: str,
    name: str,
    *,
    tier_id: int,
    datagolf_rank: int | None,
) -> SplashPlayer:
    return SplashPlayer(
        splash_player_id=splash_player_id,
        slate_player_id=f"slate-{splash_player_id}",
        slate_id="slate",
        name=name,
        tier_id=tier_id,
        datagolf_rank=datagolf_rank,
        world_rank=datagolf_rank,
        scoring_avg=None,
        country=None,
        is_selectable=True,
        attributes={},
        inputs_hash=f"hash-{splash_player_id}",
    )


def _portfolio_candidate(
    lineup_id: str,
    player_ids: tuple[str, ...],
    *,
    expected_payout: float,
    variance: float,
    config,
):
    lineup = lineup_from_players(lineup_id=lineup_id, player_ids=player_ids, entry_fee_cents=100)
    result = SplashLineupSimulationResult(
        lineup_id=lineup_id,
        simulations=2,
        expected_payout_cents=expected_payout,
        roi=(expected_payout - 100) / 100,
        cash_probability=1.0,
        top_10_probability=1.0,
        win_probability=0.5,
        profit_variance_cents=variance,
        drawdown_contribution_cents=0.0,
        mean_score=1.0,
        inputs_hash=f"result-{lineup_id}",
    )
    return portfolio_candidate_from_result(
        lineup=lineup,
        simulation_result=result,
        bankroll_cents=config.bankroll_cents,
        half_kelly_fraction=config.half_kelly_fraction,
    )
