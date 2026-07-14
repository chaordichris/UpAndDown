from __future__ import annotations

from scripts.build_splash_proxy_score_anchors import build_proxy_score_anchors


def test_build_proxy_score_anchors_rank_scales_score_moments() -> None:
    todo_rows = [
        _todo_row("best", "Best Player", 10, 0.8),
        _todo_row("worst", "Worst Player", 110, 0.5),
    ]

    anchors, review = build_proxy_score_anchors(
        todo_rows,
        best_made_cut_mean=-8.0,
        worst_made_cut_mean=-2.0,
        best_cut_rounds_mean=1.0,
        worst_cut_rounds_mean=5.0,
        made_cut_score_sd=5.5,
        cut_rounds_score_sd=4.0,
    )

    assert [anchor["player_name"] for anchor in anchors] == ["Best Player", "Worst Player"]
    assert anchors[0]["made_cut_score_mean"] == -8.0
    assert anchors[1]["made_cut_score_mean"] == -2.0
    assert anchors[0]["cut_rounds_score_mean"] == 1.0
    assert anchors[1]["cut_rounds_score_mean"] == 5.0
    assert anchors[0]["source"] == "proxy_rank_scaled_score_anchor_for_splash_sensitivity"
    assert "must not be treated as observed DataGolf" in review["policy"]
    assert review["inputs_hash"]


def _todo_row(
    player_id: str,
    player_name: str,
    datagolf_rank: int,
    make_cut_probability: float,
) -> dict:
    return {
        "player_id": player_id,
        "player_name": player_name,
        "datagolf_rank": datagolf_rank,
        "make_cut_probability": make_cut_probability,
        "raw_datagolf_player_name": player_name,
        "win_probability": 0.01,
        "top_10_probability": 0.1,
        "top_20_probability": 0.2,
    }
