"""
Configuration loading for UpAndDown.

Settings are loaded from two sources:
  1. config/settings.yaml  — non-secret parameters (checked into git)
  2. .env                  — secrets and environment-specific values (never committed)

Usage:
    from src.config import get_settings, get_books
    settings = get_settings()
    books = get_books()
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root is one level up from src/
_PROJECT_ROOT = Path(__file__).parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "config"


# ---------------------------------------------------------------------------
# Secrets and environment-specific values (from .env)
# ---------------------------------------------------------------------------

class Secrets(BaseSettings):
    """Environment variables loaded from .env. Fail fast if required keys are missing."""

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    datagolf_api_key: str = Field(default="", description="DataGolf API key")
    database_url: str = Field(
        default="sqlite:///./data/db/golf_trading.db",
        description="SQLAlchemy database URL",
    )
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    @field_validator("datagolf_api_key")
    @classmethod
    def warn_if_empty(cls, v: str) -> str:
        if not v:
            # Warn but don't raise — Phase 0 may not have a key yet
            import warnings
            warnings.warn(
                "DATAGOLF_API_KEY is not set. DataGolf ingestion will fail.",
                stacklevel=2,
            )
        return v


# ---------------------------------------------------------------------------
# Typed wrappers around settings.yaml sections
# ---------------------------------------------------------------------------

class PipelineConfig:
    def __init__(self, d: dict[str, Any]) -> None:
        self.datagolf_poll_interval_hours: int = d["datagolf_poll_interval_hours"]
        self.odds_poll_interval_hours: int = d["odds_poll_interval_hours"]
        self.odds_staleness_threshold_hours: int = d["odds_staleness_threshold_hours"]


class BankrollConfig:
    def __init__(self, d: dict[str, Any]) -> None:
        self.reserve_fraction: float = d["reserve_fraction"]
        self.active_core_fraction: float = d["active_core_fraction"]
        self.convex_fraction: float = d["convex_fraction"]

        total = self.reserve_fraction + self.active_core_fraction + self.convex_fraction
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"Bankroll fractions must sum to 1.0, got {total:.3f}"
            )


class SizingConfig:
    def __init__(self, d: dict[str, Any]) -> None:
        self.kelly_fraction: float = d["kelly_fraction"]
        self.posterior_kelly_enabled: bool = d.get("posterior_kelly_enabled", False)
        self.convex_unit_fraction: float = d["convex_unit_fraction"]
        self.min_bet_dollars: float = d["min_bet_dollars"]
        self.max_bet_fraction: float = d["max_bet_fraction"]


class ExposureConfig:
    def __init__(self, d: dict[str, Any]) -> None:
        self.max_golfer_fraction: float = d["max_golfer_fraction"]
        self.max_tournament_fraction: float = d["max_tournament_fraction"]
        self.max_book_fraction: float = d["max_book_fraction"]


class EdgeConfig:
    def __init__(self, d: dict[str, Any]) -> None:
        self.min_edge_core: float = d["min_edge_core"]
        self.min_edge_convex: float = d["min_edge_convex"]
        self.fdr_enabled: bool = d.get("fdr_enabled", False)
        self.fdr_q_core: float = d.get("fdr_q_core", 0.20)
        self.fdr_q_convex: float = d.get("fdr_q_convex", 0.10)


class DrawdownConfig:
    def __init__(self, d: dict[str, Any]) -> None:
        self.alert_threshold: float = d["alert_threshold"]
        self.reduce_threshold: float = d["reduce_threshold"]
        self.severe_threshold: float = d["severe_threshold"]
        self.paper_only_threshold: float = d["paper_only_threshold"]
        self.halt_threshold: float = d["halt_threshold"]


class RiskOfRuinConfig:
    def __init__(self, d: dict[str, Any]) -> None:
        self.bet_count: int = d["bet_count"]
        self.simulations: int = d["simulations"]
        self.seed: int = d["seed"]


class VigRemovalConfig:
    def __init__(self, d: dict[str, Any]) -> None:
        self.two_way_method: str = d["two_way_method"]
        self.multi_way_method: str = d["multi_way_method"]


class Settings:
    """Full settings object combining secrets + YAML config."""

    def __init__(self, secrets: Secrets, yaml_data: dict[str, Any]) -> None:
        self.secrets = secrets
        self.pipeline = PipelineConfig(yaml_data["pipeline"])
        self.bankroll = BankrollConfig(yaml_data["bankroll"])
        self.sizing = SizingConfig(yaml_data["sizing"])
        self.exposure = ExposureConfig(yaml_data["exposure"])
        self.edge = EdgeConfig(yaml_data["edge"])
        self.drawdown = DrawdownConfig(yaml_data["drawdown"])
        self.ror = RiskOfRuinConfig(yaml_data["ror"])
        self.vig_removal = VigRemovalConfig(yaml_data["vig_removal"])

        # Convenience pass-throughs from secrets
        self.database_url: str = secrets.database_url
        self.app_env: str = secrets.app_env
        self.log_level: str = secrets.log_level


class BookMarketConfig:
    def __init__(self, d: dict[str, Any]) -> None:
        self.display_name: str = d["display_name"]
        self.n_players: int = d["n_players"]
        self.sleeve: str = d["sleeve"]


class BookConfig:
    def __init__(self, book_id: str, d: dict[str, Any]) -> None:
        self.book_id: str = d.get("book_id", book_id)
        self.display_name: str = d["display_name"]
        self.active: bool = d["active"]
        self.markets: list[str] = d["markets"]
        self.settlement_rules: dict[str, str] = d["settlement_rules"]


class BooksConfig:
    def __init__(self, yaml_data: dict[str, Any]) -> None:
        self.books: dict[str, BookConfig] = {
            book.book_id: book
            for yaml_id, book_data in yaml_data["books"].items()
            for book in [BookConfig(yaml_id, book_data)]
        }
        self.market_types: dict[str, BookMarketConfig] = {
            market_id: BookMarketConfig(market_data)
            for market_id, market_data in yaml_data["market_types"].items()
        }

    def active_books(self) -> list[BookConfig]:
        return [b for b in self.books.values() if b.active]

    def get_settlement_rule(self, book_id: str, rule_key: str) -> str:
        book = self.books.get(book_id)
        if book is None:
            raise KeyError(f"Unknown book: {book_id}")
        return book.settlement_rules.get(rule_key, "unknown")


# ---------------------------------------------------------------------------
# Cached loaders — call these from anywhere in the app
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache the full settings object. Call once; reuse everywhere."""
    secrets = Secrets()
    yaml_path = _CONFIG_DIR / "settings.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"settings.yaml not found at {yaml_path}")
    with open(yaml_path) as f:
        yaml_data = yaml.safe_load(f)
    return Settings(secrets, yaml_data)


@lru_cache(maxsize=1)
def get_books() -> BooksConfig:
    """Load and cache the books configuration."""
    yaml_path = _CONFIG_DIR / "books.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"books.yaml not found at {yaml_path}")
    with open(yaml_path) as f:
        yaml_data = yaml.safe_load(f)
    return BooksConfig(yaml_data)


def clear_config_cache() -> None:
    """Clear the lru_cache — useful in tests that need fresh config."""
    get_settings.cache_clear()
    get_books.cache_clear()
