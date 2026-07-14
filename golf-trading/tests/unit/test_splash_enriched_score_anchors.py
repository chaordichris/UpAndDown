from __future__ import annotations

from scripts.build_splash_enriched_score_anchors import (
    SOURCE,
    build_enriched_score_anchors,
)


def test_build_enriched_score_anchors_uses_datagolf_decomposition_transform() -> None:
    rank_rows = [
        {"player_id": "24968", "player_name": "Ben Griffin", "datagolf_rank": 18},
    ]
    pre_tournament = {
        "event_name": "John Deere Classic",
        "last_updated": "2026-07-01 13:24:11 UTC",
        "baseline": [
            {
                "dg_id": 24968,
                "player_name": "Griffin, Ben",
                "make_cut": 0.8172,
                "win": 0.057,
                "top_5": 0.20,
                "top_10": 0.32,
                "top_20": 0.49,
                "top_50": 0.75,
            }
        ],
    }
    decompositions = {
        "last_updated": "2026-07-01 13:29:58 UTC",
        "players": [
            {
                "dg_id": 24968,
                "player_name": "Griffin, Ben",
                "baseline_pred": 1.34,
                "final_pred": 1.5,
                "std_deviation": 2.0,
                "sample_size": 150,
            }
        ],
    }
    fantasy = {
        "last_updated": "2026-07-02 07:01:01 UTC",
        "projections": [
            {
                "dg_id": 24968,
                "player_name": "Griffin, Ben",
                "proj_points_total": 88.92,
                "proj_ownership": 26.47,
                "std_dev": 34.06,
            }
        ],
    }

    anchors, review = build_enriched_score_anchors(
        rank_rows,
        pre_tournament,
        decompositions,
        fantasy_projections=fantasy,
        tournament_rounds=4,
        cut_rounds_played=2,
        made_cut_extra_sd=1.5,
        cut_rounds_extra_sd=1.0,
        missed_cut_relative_score_mean=2.0,
        minimum_score_sd=1.0,
    )

    assert anchors == [
        {
            "player_id": "24968",
            "player_name": "Ben Griffin",
            "datagolf_rank": 18,
            "make_cut_probability": 0.8172,
            "made_cut_score_mean": -6.0,
            "made_cut_score_sd": 4.272,
            "cut_rounds_score_mean": -1.0,
            "cut_rounds_score_sd": 3.0,
            "source": SOURCE,
            "datagolf_inputs": {
                "raw_datagolf_player_name": "Griffin, Ben",
                "decomposition_player_name": "Griffin, Ben",
                "fantasy_projection_player_name": "Griffin, Ben",
                "final_pred_sg_per_round": 1.5,
                "baseline_pred_sg_per_round": 1.34,
                "std_deviation_sg_per_round": 2.0,
                "sample_size": 150,
                "win_probability": 0.057,
                "top_5_probability": 0.20,
                "top_10_probability": 0.32,
                "top_20_probability": 0.49,
                "top_50_probability": 0.75,
                "draftkings_projected_points_total": 88.92,
                "draftkings_projected_ownership": 26.47,
                "draftkings_projection_std_dev": 34.06,
            },
        }
    ]
    assert review["review_items"] == []
    assert "not observed total-strokes score distributions" in review["policy"]
    assert review["inputs_hash"]


def test_build_enriched_score_anchors_reviews_missing_required_rows() -> None:
    rank_rows = [
        {"player_id": "24968", "player_name": "Ben Griffin", "datagolf_rank": 18},
        {"player_id": "13508", "player_name": "Jhonattan Vegas", "datagolf_rank": 222},
    ]
    pre_tournament = {
        "baseline": [
            {
                "dg_id": 24968,
                "player_name": "Griffin, Ben",
                "make_cut": 0.8172,
            }
        ],
    }
    decompositions = {
        "players": [
            {
                "dg_id": 13508,
                "player_name": "Vegas, Jhonattan",
                "final_pred": -0.2,
                "std_deviation": 2.5,
            }
        ],
    }

    anchors, review = build_enriched_score_anchors(
        rank_rows,
        pre_tournament,
        decompositions,
        fantasy_projections=None,
        tournament_rounds=4,
        cut_rounds_played=2,
        made_cut_extra_sd=1.5,
        cut_rounds_extra_sd=1.0,
        missed_cut_relative_score_mean=2.0,
        minimum_score_sd=1.0,
    )

    assert anchors == []
    assert review["review_items"] == [
        {
            "player_id": "24968",
            "player_name": "Ben Griffin",
            "datagolf_rank": 18,
            "status": "missing_datagolf_player_decomposition",
        },
        {
            "player_id": "13508",
            "player_name": "Jhonattan Vegas",
            "datagolf_rank": 222,
            "status": "missing_datagolf_pretournament_forecast",
        },
    ]


def test_build_enriched_score_anchors_reviews_missing_optional_fantasy_projection() -> None:
    rank_rows = [
        {"player_id": "24968", "player_name": "Ben Griffin", "datagolf_rank": 18},
    ]
    pre_tournament = {
        "baseline": [
            {
                "dg_id": 24968,
                "player_name": "Griffin, Ben",
                "make_cut": 0.8172,
            }
        ],
    }
    decompositions = {
        "players": [
            {
                "dg_id": 24968,
                "player_name": "Griffin, Ben",
                "final_pred": 1.5,
                "std_deviation": 2.0,
            }
        ],
    }

    anchors, review = build_enriched_score_anchors(
        rank_rows,
        pre_tournament,
        decompositions,
        fantasy_projections={"projections": []},
        tournament_rounds=4,
        cut_rounds_played=2,
        made_cut_extra_sd=1.5,
        cut_rounds_extra_sd=1.0,
        missed_cut_relative_score_mean=2.0,
        minimum_score_sd=1.0,
    )

    assert len(anchors) == 1
    assert review["review_items"] == [
        {
            "player_id": "24968",
            "player_name": "Ben Griffin",
            "datagolf_rank": 18,
            "status": "missing_optional_fantasy_projection",
        }
    ]
