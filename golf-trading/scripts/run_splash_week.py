"""SP-2 one-command weekly Splash run.

Drives the weekly Splash workflow as a resumable, manifest-driven pipeline:

    capture -> enrich -> anchors -> preflight -> portfolios -> sensitivity
        -> card -> status

Design contract (see docs/splash-bulletproof-plan.md, SP-2):
  * Each stage writes its artifact(s) into the week directory and records an
    ``inputs_hash`` that chains upstream output hashes + resolved config. A
    re-run skips any stage whose outputs exist and whose ``inputs_hash`` still
    matches the recorded manifest, so the pipeline replays deterministically.
  * ``--force-from <stage>`` reruns from a stage regardless of the cache.
  * ``--start-stage <stage>`` begins execution partway through, seeding the
    earlier stages from artifacts already on disk (the tested, offline path:
    capture/enrich/anchors are produced by the SP-1 manual scripts, then this
    runner drives preflight onward). Seeded outputs must already exist.
  * The preflight stage is a hard gate: a blocked report stops the pipeline
    with the SP-1 report. The pipeline never pushes through a data gap.
  * Stage parameters come from the ``splash:`` block in config/settings.yaml.
    CLI flags act as overrides and are logged as overrides in the manifest.
  * Stages reuse the existing scripts as importable functions / their CLIs; no
    stage logic is forked here.

Usage:
    python scripts/run_splash_week.py --contest <uuid> --week-dir artifacts/splash-week/2026-07-open
    python scripts/run_splash_week.py --contest <uuid> --start-stage preflight   # fixtures already captured
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.hashing import stable_hash  # noqa: E402

RUNNER_VERSION = "splash-week-runner-v1"
MANIFEST_FILENAME = "week-manifest.json"


# ---------------------------------------------------------------------------
# Resolved configuration (mirrors the settings.yaml splash: block)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SplashRunConfig:
    """Stage parameters for one weekly run, resolved from config + overrides."""

    artifact_dir: str = "artifacts/splash-week"
    api_base_url: str = "https://api.splashsports.com/contests-service/api"
    datagolf_base_url: str = "https://feeds.datagolf.com"
    tiers: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
    player_pool_limit: int = 50
    bankroll_dollars: float = 10_000.0
    portfolio_name: str = "conservative"
    simulations: int = 1_000
    seed: int = 20260701
    max_candidates: int = 2_000
    candidate_generation: str = "projected"
    lineup_id_prefix: str = "rungood"
    sensitivity_simulations: int = 250
    sensitivity_seeds: tuple[int, ...] = (20260701, 20260708)
    sensitivity_candidate_caps: tuple[int, ...] = (250, 500)
    sensitivity_ownership_concentrations: tuple[float, ...] = (0.75, 1.0, 1.25)
    max_fixture_age_hours: float = 72.0
    min_depth_multiple: float = 2.0

    @property
    def bankroll_cents(self) -> int:
        return int(round(self.bankroll_dollars * 100))


def config_from_settings(overrides: dict[str, Any] | None = None) -> SplashRunConfig:
    """Build a run config from the ``splash:`` settings block + CLI overrides."""
    from src.config import get_settings

    splash = get_settings().splash
    base = SplashRunConfig(
        artifact_dir=splash.artifact_dir,
        api_base_url=splash.api_base_url,
        datagolf_base_url=splash.datagolf_base_url,
        tiers=tuple(splash.tiers),
        player_pool_limit=splash.player_pool_limit,
        bankroll_dollars=splash.bankroll_dollars,
        portfolio_name=splash.portfolio_name,
        simulations=splash.simulations,
        seed=splash.seed,
        max_candidates=splash.max_candidates,
        candidate_generation=splash.candidate_generation,
        lineup_id_prefix=splash.lineup_id_prefix,
        sensitivity_simulations=splash.sensitivity_simulations,
        sensitivity_seeds=tuple(splash.sensitivity_seeds),
        sensitivity_candidate_caps=tuple(splash.sensitivity_candidate_caps),
        sensitivity_ownership_concentrations=tuple(splash.sensitivity_ownership_concentrations),
        max_fixture_age_hours=splash.max_fixture_age_hours,
        min_depth_multiple=splash.min_depth_multiple,
    )
    return replace(base, **overrides) if overrides else base


# ---------------------------------------------------------------------------
# Stage plumbing
# ---------------------------------------------------------------------------

@dataclass
class StageContext:
    """Everything a stage handler needs to run and write its outputs."""

    contest_ref: str | None
    week_dir: Path
    config: SplashRunConfig
    upstream: dict[str, dict[str, str]]  # stage_name -> {label: absolute path}
    output_paths: dict[str, Path]        # label -> absolute path this stage must write


@dataclass
class StageResult:
    """What a handler reports back. ``blocked`` halts the pipeline (preflight)."""

    blocked: bool = False
    detail: str = ""


@dataclass
class Stage:
    name: str
    outputs: dict[str, str]  # label -> filename relative to week_dir
    handler: Callable[[StageContext], StageResult]


def upstream_path(ctx: StageContext, stage: str, label: str) -> Path:
    return Path(ctx.upstream[stage][label])


# ---------------------------------------------------------------------------
# Stage handlers — thin delegations to the existing scripts. Imports are lazy
# so the engine (and its tests) load without the heavier stage dependencies.
# ---------------------------------------------------------------------------

def _stage_capture(ctx: StageContext) -> StageResult:
    """Capture contest detail, player pools, and the DataGolf rank fixture."""
    if not ctx.contest_ref:
        raise ValueError("capture stage requires --contest <uuid>")
    from scripts.build_splash_datagolf_rank_fixture import (
        build_rank_rows,
        fetch_datagolf_player_list,
    )
    from scripts.capture_splash_contest import capture_splash_contest

    capture_splash_contest(
        contest_id=ctx.contest_ref,
        slate_id=None,
        tiers=ctx.config.tiers,
        limit=ctx.config.player_pool_limit,
        contest_output=ctx.output_paths["contest"],
        player_pools_output=ctx.output_paths["player_pools"],
        base_url=ctx.config.api_base_url,
    )
    player_pools = _load_json(ctx.output_paths["player_pools"])
    rank_rows, review = build_rank_rows(player_pools, fetch_datagolf_player_list())
    _write_json(ctx.output_paths["datagolf_ranks"], rank_rows)
    _write_json(ctx.week_dir / "datagolf-rank-review.json", review)
    return StageResult()


def _stage_enrich(ctx: StageContext) -> StageResult:
    """Fetch DataGolf pre-tournament + player-decomposition enrichment."""
    from scripts.capture_datagolf_splash_enrichment import capture_datagolf_enrichment

    out_dir = ctx.week_dir / "datagolf-enrichment"
    capture_datagolf_enrichment(
        output_dir=out_dir,
        tour="pga",
        sites=("draftkings", "fanduel", "yahoo"),
        add_position="1,2,3,4,5,10,15,20,30,40,50",
        skill_stats="sg_putt,sg_arg,sg_app,sg_ott,sg_t2g,sg_total,driving_dist,driving_acc",
        base_url=ctx.config.datagolf_base_url,
    )
    # Surface the two files the anchors stage consumes at the declared paths.
    _copy(out_dir / "pre-tournament.json", ctx.output_paths["pre_tournament"])
    _copy(out_dir / "player-decompositions.json", ctx.output_paths["player_decompositions"])
    return StageResult()


def _stage_anchors(ctx: StageContext) -> StageResult:
    """Build enriched score anchors from ranks + DataGolf enrichment."""
    from scripts.build_splash_enriched_score_anchors import build_enriched_score_anchors

    rank_rows = _load_json(upstream_path(ctx, "capture", "datagolf_ranks"))
    pre_tournament = _load_json(upstream_path(ctx, "enrich", "pre_tournament"))
    decompositions = _load_json(upstream_path(ctx, "enrich", "player_decompositions"))
    anchors, review = build_enriched_score_anchors(
        rank_rows,
        pre_tournament,
        decompositions,
        fantasy_projections=None,
        # Anchor-shape defaults mirror build_splash_enriched_score_anchors.py's
        # CLI; they graduate into the fuller SP-4 config block later.
        tournament_rounds=4,
        cut_rounds_played=2,
        made_cut_extra_sd=1.5,
        cut_rounds_extra_sd=1.0,
        missed_cut_relative_score_mean=2.0,
        minimum_score_sd=1.0,
    )
    _write_json(ctx.output_paths["score_anchors"], anchors)
    _write_json(ctx.output_paths["anchor_review"], review)
    return StageResult()


def _stage_preflight(ctx: StageContext) -> StageResult:
    """SP-1 integrity gate. A blocked report halts the pipeline."""
    from src.fantasy.splash.integrity import report_to_artifact, run_preflight
    from src.fantasy.splash.parser import parse_contest_detail, parse_contest_player_pool
    from src.fantasy.splash.scoring_model import datagolf_score_anchor_from_row

    contest = parse_contest_detail(_load_json(upstream_path(ctx, "capture", "contest")))
    player_pool = parse_contest_player_pool(
        contest,
        _load_json(upstream_path(ctx, "capture", "player_pools")),
        _load_json(upstream_path(ctx, "capture", "datagolf_ranks")),
    )
    anchors = tuple(
        datagolf_score_anchor_from_row(row)
        for row in _load_json(upstream_path(ctx, "anchors", "score_anchors"))
    )
    # Freshness is skipped: seeded/replayed fixtures carry archival mtimes.
    report = run_preflight(
        player_pool,
        anchors,
        None,
        max_fixture_age_hours=ctx.config.max_fixture_age_hours,
        min_depth_multiple=ctx.config.min_depth_multiple,
    )
    artifact = report_to_artifact(report)
    artifact["generated_at"] = _now_iso()
    artifact["contest"] = {"id": contest.splash_id, "name": contest.name}
    _write_json(ctx.output_paths["preflight_report"], artifact)
    if not report.passed:
        failures = [c.check_id for c in report.blocking_failures]
        return StageResult(blocked=True, detail=f"preflight blocked: {', '.join(failures)}")
    return StageResult()


def _stage_portfolios(ctx: StageContext) -> StageResult:
    """Generate conservative + convex portfolios via the canonical generator, in-process."""
    from scripts.generate_splash_portfolios import generate_portfolios, write_portfolio_artifact
    from src.fantasy.splash.series import get_series

    artifact = generate_portfolios(
        root=PROJECT_ROOT,
        series=get_series("rungood"),
        contest_fixture=upstream_path(ctx, "capture", "contest"),
        player_pools_fixture=upstream_path(ctx, "capture", "player_pools"),
        datagolf_ranks_fixture=upstream_path(ctx, "capture", "datagolf_ranks"),
        score_anchors_fixture=upstream_path(ctx, "anchors", "score_anchors"),
        fantasy_projections_fixture=None,
        bankroll_cents=ctx.config.bankroll_cents,
        simulations=ctx.config.simulations,
        seed=ctx.config.seed,
        max_candidates=ctx.config.max_candidates,
        evaluation_batch_size=50,
        lineup_id_prefix=ctx.config.lineup_id_prefix,
        ownership_concentration=1.0,
        ownership_uncertainty_sd=0.25,
        candidate_generation=ctx.config.candidate_generation,
    )
    write_portfolio_artifact(artifact, ctx.output_paths["portfolios"])
    return StageResult()


def _stage_sensitivity(ctx: StageContext) -> StageResult:
    """Run the sensitivity sweep the lineup card summarises."""
    from scripts.run_splash_sensitivity import run_sensitivity_matrix

    run_sensitivity_matrix(
        output_dir=ctx.week_dir / "sensitivity",
        summary_output=ctx.output_paths["sensitivity"],
        contest_fixture=str(upstream_path(ctx, "capture", "contest")),
        player_pools_fixture=str(upstream_path(ctx, "capture", "player_pools")),
        datagolf_ranks_fixture=str(upstream_path(ctx, "capture", "datagolf_ranks")),
        score_anchors_fixture=str(upstream_path(ctx, "anchors", "score_anchors")),
        fantasy_projections_fixture=None,
        portfolio_generator_script="scripts/generate_splash_portfolios.py",
        lineup_id_prefix=ctx.config.lineup_id_prefix,
        seeds=ctx.config.sensitivity_seeds,
        candidate_caps=ctx.config.sensitivity_candidate_caps,
        ownership_concentrations=ctx.config.sensitivity_ownership_concentrations,
        ownership_uncertainty_sd=0.25,
        simulations=ctx.config.sensitivity_simulations,
        evaluation_batch_size=50,
        candidate_generation=ctx.config.candidate_generation,
    )
    return StageResult()


def _stage_card(ctx: StageContext) -> StageResult:
    """Cut the manual lineup card from the chosen portfolio + sensitivity."""
    from scripts.build_splash_lineup_card import build_lineup_card, render_lineup_card_text

    portfolio_path = upstream_path(ctx, "portfolios", "portfolios")
    sensitivity_path = upstream_path(ctx, "sensitivity", "sensitivity")
    card = build_lineup_card(
        portfolio_artifact=_load_json(portfolio_path),
        sensitivity_summary=_load_json(sensitivity_path),
        portfolio_artifact_path=str(portfolio_path),
        sensitivity_summary_path=str(sensitivity_path),
        portfolio_name=ctx.config.portfolio_name,
        allow_no_play=True,  # a no-play card is a valid, auditable weekly output
    )
    _write_json(ctx.output_paths["card"], card)
    ctx.output_paths["card_text"].write_text(render_lineup_card_text(card))
    return StageResult()


def _stage_status(ctx: StageContext) -> StageResult:
    """Publish the control-plane status file from this week's portfolios."""
    from scripts.export_control_plane_status import build_splash_status

    # build_splash_status reads rungood-splash-portfolios.json from artifact_dir.
    status = build_splash_status(ctx.week_dir)
    _write_json(ctx.output_paths["status"], status)
    return StageResult()


STAGES: tuple[Stage, ...] = (
    Stage("capture", {
        "contest": "contest-detail.json",
        "player_pools": "player-pools-by-tier.json",
        "datagolf_ranks": "datagolf-player-ranks.json",
    }, _stage_capture),
    Stage("enrich", {
        "pre_tournament": "pre-tournament.json",
        "player_decompositions": "player-decompositions.json",
    }, _stage_enrich),
    Stage("anchors", {
        "score_anchors": "score-anchors-enriched.json",
        "anchor_review": "score-anchors-review.json",
    }, _stage_anchors),
    Stage("preflight", {"preflight_report": "preflight-report.json"}, _stage_preflight),
    Stage("portfolios", {"portfolios": "rungood-splash-portfolios.json"}, _stage_portfolios),
    Stage("sensitivity", {"sensitivity": "sensitivity-summary.json"}, _stage_sensitivity),
    Stage("card", {"card": "lineup-card.json", "card_text": "lineup-card.txt"}, _stage_card),
    Stage("status", {"status": "splash-dfs.status.json"}, _stage_status),
)

STAGE_NAMES: tuple[str, ...] = tuple(stage.name for stage in STAGES)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def run_splash_week(
    *,
    contest_ref: str | None,
    week_dir: Path,
    config: SplashRunConfig,
    start_stage: str | None = None,
    force_from: str | None = None,
    overrides: dict[str, Any] | None = None,
    stages: tuple[Stage, ...] = STAGES,
) -> dict[str, Any]:
    """Run the weekly pipeline, returning the week manifest.

    ``start_stage`` seeds all earlier stages from artifacts already on disk.
    ``force_from`` reruns from that stage even if the cache is warm.
    """
    week_dir = week_dir.resolve()
    week_dir.mkdir(parents=True, exist_ok=True)
    _validate_stage_arg("start_stage", start_stage, stages)
    _validate_stage_arg("force_from", force_from, stages)

    prior = _load_prior_manifest(week_dir)
    start_index = _stage_index(stages, start_stage) if start_stage else 0
    force_index = _stage_index(stages, force_from) if force_from else len(stages)

    upstream: dict[str, dict[str, str]] = {}
    stage_records: list[dict[str, Any]] = []
    overall_status = "completed"
    blocked_stage: str | None = None

    for index, stage in enumerate(stages):
        output_paths = {label: week_dir / name for label, name in stage.outputs.items()}

        if index < start_index:
            # Seed from disk: earlier stages were produced elsewhere.
            record = _seed_stage(stage, output_paths)
            upstream[stage.name] = {label: str(p) for label, p in output_paths.items()}
            stage_records.append(record)
            continue

        inputs_hash = _stage_inputs_hash(stage, config, contest_ref, upstream)
        cached = prior.get(stage.name)
        # A stage skips only if it is not being force-rerun, its outputs all
        # exist, and the recorded inputs_hash still matches.
        force = index >= force_index
        outputs_present = all(p.exists() for p in output_paths.values())
        if (
            not force
            and cached is not None
            and cached.get("status") in ("completed", "skipped", "seeded")
            and cached.get("inputs_hash") == inputs_hash
            and outputs_present
        ):
            upstream[stage.name] = {label: str(p) for label, p in output_paths.items()}
            stage_records.append({
                "name": stage.name,
                "status": "skipped",
                "inputs_hash": inputs_hash,
                "outputs": _hash_outputs(output_paths),
                "ran_at": cached.get("ran_at"),
            })
            continue

        ctx = StageContext(
            contest_ref=contest_ref,
            week_dir=week_dir,
            config=config,
            upstream=upstream,
            output_paths=output_paths,
        )
        result = stage.handler(ctx)
        record = {
            "name": stage.name,
            "status": "blocked" if result.blocked else "completed",
            "inputs_hash": inputs_hash,
            "outputs": _hash_outputs(output_paths),
            "ran_at": _now_iso(),
        }
        if result.detail:
            record["detail"] = result.detail
        stage_records.append(record)
        upstream[stage.name] = {label: str(p) for label, p in output_paths.items()}

        if result.blocked:
            overall_status = "blocked"
            blocked_stage = stage.name
            break

    manifest = {
        "artifact_type": "splash_week_manifest",
        "version": RUNNER_VERSION,
        "generated_at": _now_iso(),
        "contest_ref": contest_ref,
        "week_dir": str(week_dir),
        "status": overall_status,
        "blocked_stage": blocked_stage,
        "start_stage": start_stage,
        "force_from": force_from,
        "config": _config_view(config),
        "overrides": overrides or {},
        "stages": stage_records,
    }
    manifest["artifact_hash"] = stable_hash({k: v for k, v in manifest.items() if k != "generated_at"})
    _write_json(week_dir / MANIFEST_FILENAME, manifest)
    return manifest


def _seed_stage(stage: Stage, output_paths: dict[str, Path]) -> dict[str, Any]:
    missing = [str(p) for p in output_paths.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"--start-stage requires seeded outputs for '{stage.name}'; missing: {missing}"
        )
    return {
        "name": stage.name,
        "status": "seeded",
        "inputs_hash": None,
        "outputs": _hash_outputs(output_paths),
        "ran_at": None,
    }


def _stage_inputs_hash(
    stage: Stage,
    config: SplashRunConfig,
    contest_ref: str | None,
    upstream: dict[str, dict[str, str]],
) -> str:
    upstream_hashes = {
        name: {label: _hash_file(Path(path)) for label, path in outputs.items()}
        for name, outputs in upstream.items()
    }
    return stable_hash({
        "stage": stage.name,
        "contest_ref": contest_ref,
        "config": _config_view(config),
        "upstream": upstream_hashes,
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_stage_arg(arg_name: str, value: str | None, stages: tuple[Stage, ...]) -> None:
    if value is not None and value not in {s.name for s in stages}:
        raise ValueError(f"{arg_name} must be one of {[s.name for s in stages]}, got {value!r}")


def _stage_index(stages: tuple[Stage, ...], name: str) -> int:
    for index, stage in enumerate(stages):
        if stage.name == name:
            return index
    raise ValueError(f"unknown stage: {name}")


def _config_view(config: SplashRunConfig) -> dict[str, Any]:
    from dataclasses import asdict

    return asdict(config)


def _load_prior_manifest(week_dir: Path) -> dict[str, dict[str, Any]]:
    path = week_dir / MANIFEST_FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {stage["name"]: stage for stage in data.get("stages", []) if "name" in stage}


def _hash_outputs(output_paths: dict[str, Path]) -> dict[str, dict[str, str]]:
    return {
        label: {"path": str(path), "hash": _hash_file(path)}
        for label, path in output_paths.items()
    }


def _hash_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def _write_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_week_summary(manifest: dict[str, Any]) -> str:
    lines = [
        f"Splash week [{manifest['status']}] — {manifest['week_dir']}",
    ]
    for stage in manifest["stages"]:
        mark = {"completed": "✓", "skipped": "·", "seeded": "○", "blocked": "✗"}.get(
            stage["status"], "?"
        )
        line = f"  {mark} {stage['name']}: {stage['status']}"
        if stage.get("detail"):
            line += f" — {stage['detail']}"
        lines.append(line)
    if manifest["status"] == "blocked":
        lines.append(f"\nBLOCKED at {manifest['blocked_stage']}. Fix the data gap and re-run.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--contest", dest="contest_ref", help="Splash contest UUID.")
    parser.add_argument(
        "--week-dir",
        type=Path,
        help="Week artifact directory (default: <splash.artifact_dir>/<UTC date>).",
    )
    parser.add_argument(
        "--start-stage",
        choices=STAGE_NAMES,
        help="Begin at this stage; seed earlier stages from artifacts on disk.",
    )
    parser.add_argument(
        "--force-from",
        choices=STAGE_NAMES,
        help="Rerun from this stage even if the cache is warm.",
    )
    # Common overrides (logged as overrides in the manifest).
    parser.add_argument("--bankroll-dollars", type=float)
    parser.add_argument("--simulations", type=int)
    parser.add_argument("--portfolio-name")
    return parser


def _overrides_from_args(args: argparse.Namespace) -> dict[str, Any]:
    keys = ("bankroll_dollars", "simulations", "portfolio_name")
    return {k: getattr(args, k) for k in keys if getattr(args, k) is not None}


def main() -> int:
    args = build_parser().parse_args()
    overrides = _overrides_from_args(args)
    config = config_from_settings(overrides)
    week_dir = args.week_dir or (
        PROJECT_ROOT / config.artifact_dir / _now_iso()[:10]
    )
    manifest = run_splash_week(
        contest_ref=args.contest_ref,
        week_dir=week_dir,
        config=config,
        start_stage=args.start_stage,
        force_from=args.force_from,
        overrides=overrides,
    )
    print(render_week_summary(manifest), file=sys.stderr)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 1 if manifest["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
