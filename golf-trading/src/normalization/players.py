"""
Player name resolution.

Maps player names from sportsbooks (which vary by book and can contain typos,
abbreviations, or alternate spellings) to canonical DataGolf player IDs.

Resolution chain (in order):
  1. Exact match on canonical name (case-insensitive, stripped).
  2. Alias lookup from the PlayerAlias table.
  3. Fuzzy match using difflib.SequenceMatcher — only accepted above a
     configurable similarity threshold (default: 0.85).

If none of the above succeeds, resolve() returns None.
Manual aliases can be added via add_alias() and are persisted to the DB.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.storage.models import Player, PlayerAlias

logger = logging.getLogger(__name__)

_DEFAULT_FUZZY_THRESHOLD = 0.85


@dataclass
class ResolveResult:
    """The outcome of a name resolution attempt."""

    datagolf_player_id: str | None
    canonical_name: str | None
    method: str  # "exact", "alias", "fuzzy", or "unresolved"
    confidence: float  # 1.0 for exact/alias; similarity score for fuzzy


class PlayerResolver:
    """Resolves book player names to canonical DataGolf player IDs.

    Backed by the Player and PlayerAlias tables from the DB.

    Args:
        session: An active SQLAlchemy session. The caller is responsible for
                 managing the session lifecycle (commit / rollback / close).
        fuzzy_threshold: Minimum similarity score (0–1) to accept a fuzzy match.
    """

    def __init__(
        self,
        session: Session,
        fuzzy_threshold: float = _DEFAULT_FUZZY_THRESHOLD,
    ) -> None:
        self._session = session
        self._fuzzy_threshold = fuzzy_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, name: str, source: str = "unknown") -> ResolveResult:
        """Resolve a player name to a DataGolf player ID.

        Args:
            name: The player name as it appears on the sportsbook.
            source: The originating book or data source (e.g., "dk", "fd", "datagolf").
                    Used only for logging; does not affect resolution logic.

        Returns:
            ResolveResult. If unresolved, datagolf_player_id and canonical_name are None.
        """
        if not name or not name.strip():
            return ResolveResult(
                datagolf_player_id=None,
                canonical_name=None,
                method="unresolved",
                confidence=0.0,
            )

        cleaned = _normalize_name(name)

        # Step 1: Exact match on canonical name
        player = self._exact_match(cleaned)
        if player is not None:
            logger.debug("Resolved %r (source=%s) by exact match → %s", name, source, player.datagolf_player_id)
            return ResolveResult(
                datagolf_player_id=player.datagolf_player_id,
                canonical_name=player.name_canonical,
                method="exact",
                confidence=1.0,
            )

        # Step 2: Alias lookup
        player = self._alias_match(cleaned, source)
        if player is not None:
            logger.debug("Resolved %r (source=%s) by alias → %s", name, source, player.datagolf_player_id)
            return ResolveResult(
                datagolf_player_id=player.datagolf_player_id,
                canonical_name=player.name_canonical,
                method="alias",
                confidence=1.0,
            )

        # Step 3: Fuzzy match
        player, score = self._fuzzy_match(cleaned)
        if player is not None:
            logger.info(
                "Resolved %r (source=%s) by fuzzy match (score=%.3f) → %s",
                name, source, score, player.datagolf_player_id,
            )
            return ResolveResult(
                datagolf_player_id=player.datagolf_player_id,
                canonical_name=player.name_canonical,
                method="fuzzy",
                confidence=score,
            )

        logger.warning("Could not resolve player name %r (source=%s)", name, source)
        return ResolveResult(
            datagolf_player_id=None,
            canonical_name=None,
            method="unresolved",
            confidence=0.0,
        )

    def add_alias(
        self,
        datagolf_player_id: str,
        alias_name: str,
        source: str,
    ) -> None:
        """Persist a manual alias for a player.

        Args:
            datagolf_player_id: The DataGolf player ID to map the alias to.
            alias_name: The alternate name (as it appears in the source).
            source: The book or data source this alias is valid for.

        Raises:
            LookupError: If datagolf_player_id is not found in the Player table.
            ValueError: If the alias already exists for this source.
        """
        player = (
            self._session.query(Player)
            .filter_by(datagolf_player_id=datagolf_player_id)
            .one_or_none()
        )
        if player is None:
            raise LookupError(
                f"Player with datagolf_player_id={datagolf_player_id!r} not found."
            )

        existing = (
            self._session.query(PlayerAlias)
            .filter_by(alias_name=_normalize_name(alias_name), source=source)
            .one_or_none()
        )
        if existing is not None:
            raise ValueError(
                f"Alias {alias_name!r} for source={source!r} already exists "
                f"(maps to {existing.player_id})."
            )

        alias = PlayerAlias(
            player_id=player.player_id,
            alias_name=_normalize_name(alias_name),
            source=source,
        )
        self._session.add(alias)
        self._session.flush()

    # ------------------------------------------------------------------
    # Private resolution helpers
    # ------------------------------------------------------------------

    def _exact_match(self, cleaned_name: str) -> Player | None:
        """Case-insensitive exact match on name_canonical."""
        return (
            self._session.query(Player)
            .filter(Player.name_canonical.ilike(cleaned_name))
            .one_or_none()
        )

    def _alias_match(self, cleaned_name: str, source: str) -> Player | None:
        """Look up alias, preferring source-specific aliases then any-source aliases."""
        # Try source-specific alias first
        alias = (
            self._session.query(PlayerAlias)
            .filter_by(alias_name=cleaned_name, source=source)
            .one_or_none()
        )
        if alias is None:
            # Fall back to alias registered without a specific source
            alias = (
                self._session.query(PlayerAlias)
                .filter_by(alias_name=cleaned_name, source="any")
                .one_or_none()
            )
        if alias is None:
            return None
        return (
            self._session.query(Player)
            .filter_by(player_id=alias.player_id)
            .one_or_none()
        )

    def _fuzzy_match(self, cleaned_name: str) -> tuple[Player | None, float]:
        """Find the best fuzzy match across all canonical player names."""
        all_players: list[Player] = self._session.query(Player).all()
        if not all_players:
            return None, 0.0

        best_player: Player | None = None
        best_score = 0.0

        for player in all_players:
            score = difflib.SequenceMatcher(
                None,
                cleaned_name.lower(),
                _normalize_name(player.name_canonical).lower(),
            ).ratio()
            if score > best_score:
                best_score = score
                best_player = player

        if best_score >= self._fuzzy_threshold:
            return best_player, best_score
        return None, best_score


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """Strip and collapse whitespace for consistent comparison."""
    return " ".join(name.strip().split())
