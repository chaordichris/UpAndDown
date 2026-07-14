from __future__ import annotations

from scripts.build_splash_datagolf_rank_fixture import build_rank_rows


def test_build_rank_rows_matches_datagolf_last_first_names() -> None:
    player_pools = {
        "1": {
            "response_body": {
                "data": [
                    _splash_player("row-1", "player-1", "Ben Griffin", 18),
                    _splash_player("row-2", "player-2", "No Match", 99),
                    _splash_player("row-3", "player-3", "No Rank", None),
                ],
                "total": 3,
                "limit": 50,
                "offset": 0,
            }
        }
    }
    datagolf_players = [
        {"dg_id": 12345, "player_name": "Griffin, Ben"},
        {"dg_id": 67890, "player_name": "Other, Player"},
    ]

    rows, review = build_rank_rows(player_pools, datagolf_players)

    assert rows == [
        {
            "player_id": "12345",
            "player_name": "Ben Griffin",
            "datagolf_rank": 18,
            "source": "datagolf_player_list_exact_name_plus_splash_datagolf_rank",
            "raw_datagolf_player_name": "Griffin, Ben",
            "splash_tier": 1,
            "splash_player_id": "player-1",
        }
    ]
    assert [item["status"] for item in review["review_items"]] == [
        "no_exact_datagolf_name_match",
        "excluded_missing_splash_datagolf_rank",
    ]
    assert review["mapped_count"] == 1
    assert review["review_count"] == 2
    assert review["inputs_hash"]


def test_build_rank_rows_applies_manual_override_with_rank_check() -> None:
    player_pools = {
        "1": {
            "response_body": {
                "data": [_splash_player("row-1", "player-1", "Hao-Tong Li", 149)],
                "total": 1,
                "limit": 50,
                "offset": 0,
            }
        }
    }

    rows, review = build_rank_rows(
        player_pools,
        datagolf_players=[],
        manual_overrides=[
            {
                "splash_player_name": "Hao-Tong Li",
                "player_id": 15310,
                "raw_datagolf_player_name": "Li, Haotong",
                "datagolf_rank": 149,
                "review_note": "DataGolf field row uses unhyphenated given name.",
            }
        ],
    )

    assert rows == [
        {
            "player_id": "15310",
            "player_name": "Hao-Tong Li",
            "datagolf_rank": 149,
            "source": "manual_datagolf_field_override",
            "raw_datagolf_player_name": "Li, Haotong",
            "splash_tier": 1,
            "splash_player_id": "player-1",
            "review_note": "DataGolf field row uses unhyphenated given name.",
        }
    ]
    assert review["manual_override_count"] == 1
    assert review["review_items"] == []


def _splash_player(
    row_id: str,
    player_id: str,
    name: str,
    datagolf_rank: int | None,
) -> dict:
    return {
        "id": row_id,
        "playerId": player_id,
        "slateId": "slate",
        "attributes": {
            "country": "UNITED STATES",
            "datagolf_rank": datagolf_rank,
        },
        "name": name,
        "isPlayerSelectable": True,
    }
