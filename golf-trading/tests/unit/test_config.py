"""
Unit tests for the config loading module.
"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml


def test_settings_load(tmp_path):
    """Settings load successfully from a valid YAML file."""
    # Point loader at real config files
    from src.config import get_settings, clear_config_cache
    clear_config_cache()
    settings = get_settings()
    assert settings.bankroll.reserve_fraction == 0.50
    assert settings.bankroll.active_core_fraction == 0.40
    assert settings.bankroll.convex_fraction == 0.10
    assert settings.sizing.kelly_fraction == 0.25
    assert settings.edge.min_edge_core == 0.03
    assert settings.edge.min_edge_convex == 0.08


def test_bankroll_fractions_sum_to_one():
    """Bankroll fractions must sum to 1.0."""
    from src.config import BankrollConfig
    config = BankrollConfig(
        {"reserve_fraction": 0.5, "active_core_fraction": 0.4, "convex_fraction": 0.1}
    )
    total = config.reserve_fraction + config.active_core_fraction + config.convex_fraction
    assert abs(total - 1.0) < 0.001


def test_bankroll_fractions_invalid():
    """BankrollConfig raises ValueError if fractions don't sum to 1.0."""
    from src.config import BankrollConfig
    with pytest.raises(ValueError, match="sum to 1.0"):
        BankrollConfig(
            {"reserve_fraction": 0.5, "active_core_fraction": 0.4, "convex_fraction": 0.2}
        )


def test_books_load():
    """Books config loads with active books."""
    from src.config import get_books, clear_config_cache
    clear_config_cache()
    books = get_books()
    active = books.active_books()
    assert len(active) >= 2
    book_ids = {b.book_id for b in active}
    assert "dk" in book_ids
    assert "fd" in book_ids


def test_books_settlement_rule():
    """Settlement rules are accessible per book."""
    from src.config import get_books, clear_config_cache
    clear_config_cache()
    books = get_books()
    rule = books.get_settlement_rule("dk", "matchup_wd_before_tee")
    assert rule == "void"


def test_books_unknown_book_raises():
    """Requesting a settlement rule for an unknown book raises KeyError."""
    from src.config import get_books, clear_config_cache
    clear_config_cache()
    books = get_books()
    with pytest.raises(KeyError):
        books.get_settlement_rule("betmgm", "matchup_wd_before_tee")


def test_market_types_loaded():
    """All expected market types are present."""
    from src.config import get_books, clear_config_cache
    clear_config_cache()
    books = get_books()
    expected = {"matchup_2ball", "matchup_3ball", "make_cut", "top_10", "top_20", "outright_win"}
    assert expected.issubset(set(books.market_types.keys()))


def test_convex_sleeve_market():
    """Outright win is classified as convex sleeve."""
    from src.config import get_books, clear_config_cache
    clear_config_cache()
    books = get_books()
    assert books.market_types["outright_win"].sleeve == "convex"


def test_core_sleeve_markets():
    """Matchup markets are classified as core sleeve."""
    from src.config import get_books, clear_config_cache
    clear_config_cache()
    books = get_books()
    assert books.market_types["matchup_2ball"].sleeve == "core"
    assert books.market_types["matchup_3ball"].sleeve == "core"
