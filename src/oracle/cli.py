"""The ``oracle`` command surface (§6.7) — the only sanctioned path from the
LLM/cron to on-disk state (§3.1).

Every subcommand is a thin wrapper that delegates the actual math/storage to
the owning module (scoring, aggregation, ledger, benchmarks, resolution,
report, calibration, importer, connectors). The CLI's own responsibilities are
narrow but load-bearing:

* it *stamps* ids, ``committed_at``/``resolved_at``, and the git SHA — the
  caller can never supply them, so the LLM cannot backdate or forge provenance
  (§5.9);
* it clamps committed probabilities to ``[0.01, 0.99]`` (log-score protection,
  §5.9 step 2);
* it enforces the update-trigger rule (>= 1 trigger, >= 3 for fragile
  forecasts, §5.9 step 4);
* on committing an *import* question it unseals the market snapshot into the
  ``market`` baseline (§5.13 step 6) — the CLI reads ``data/sealed/``, the LLM
  never does;
* it returns machine-readable exit codes for cron: ``0`` = nothing to do,
  ``10`` = a human/LLM needs to act (§10.8).

State lives under a root directory (default: ``$ORACLE_ROOT`` or the cwd),
overridable with ``--root`` so tests run against an isolated tree.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import click
from dotenv import load_dotenv

from oracle.aggregation import pool
from oracle.benchmarks import get_baselines, record_baseline
from oracle.calibration import fit_recalibration, load_active_map, save_map
from oracle.connectors import doctor, registry
from oracle.importer import (
    candidate_to_spec,
    fetch_and_filter,
    seal,
    unseal_market_baseline,
)
from oracle.ledger import Ledger
from oracle.models import (
    ForecastRecord,
    QuestionSpec,
    new_forecast_id,
    new_question_id,
)
from oracle.report import render_pnl, render_report, render_scoreboard
from oracle.resolution import build_resolution, due_forecasts, due_triggers

# Committed-probability floor/ceiling (§5.9 step 2).
_PROB_FLOOR = 0.01
_PROB_CEIL = 0.99
# Exit code signalling "a human/LLM needs to act" (§10.8).
_ATTENTION = 10


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _git_sha() -> str:
    """Current commit SHA via ``git rev-parse HEAD`` (``"unknown"`` if none)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return "unknown"
    return out.stdout.strip() if out.returncode == 0 else "unknown"


def _questions_dir(root: Path) -> Path:
    return root / "data" / "questions"


def _calibration_dir(root: Path) -> Path:
    return root / "data" / "benchmarks" / "calibration"


def _load_spec(root: Path, qid: str) -> QuestionSpec | None:
    path = _questions_dir(root) / f"{qid}.json"
    if not path.exists():
        return None
    return QuestionSpec.model_validate_json(path.read_text(encoding="utf-8"))


def _next_question_seq(root: Path, date: datetime) -> int:
    """Next 1-based sequence for ``Q-<YYYYMMDD>-NNN`` in the question store."""
    stem = f"Q-{date:%Y%m%d}-"
    max_seq = 0
    d = _questions_dir(root)
    if d.is_dir():
        for p in d.glob("Q-*.json"):
            tail = p.stem[len(stem):] if p.stem.startswith(stem) else ""
            if tail.isdigit():
                max_seq = max(max_seq, int(tail))
    return max_seq + 1


def _queued_imports(root: Path, ledger: Ledger) -> list[str]:
    """Import-origin questions with a spec on disk but no forecast yet."""
    forecasted = {r.question_id for r in ledger.all_forecasts()}
    out: list[str] = []
    d = _questions_dir(root)
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                spec = QuestionSpec.model_validate_json(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if spec.origin == "import" and spec.id not in forecasted:
                out.append(spec.id)
    return out


def _parse_days(window: str) -> int:
    return int(window.strip().lower().rstrip("d"))


# --------------------------------------------------------------------------- #
# group
# --------------------------------------------------------------------------- #
@click.group()
@click.option(
    "--root",
    type=click.Path(file_okay=False),
    default=None,
    help="Oracle state root (default: $ORACLE_ROOT or the current directory).",
)
@click.pass_context
def cli(ctx: click.Context, root: str | None) -> None:
    """Oracle — deterministic forecasting harness CLI (§6.7)."""
    ctx.ensure_object(dict)
    resolved = root or os.environ.get("ORACLE_ROOT") or os.getcwd()
    # Load secrets from .env (never committed) so connectors see their keys.
    # Real environment variables always take precedence over .env values.
    load_dotenv(Path(resolved) / ".env")
    load_dotenv(Path.cwd() / ".env")
    ctx.obj["root"] = Path(resolved)


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Due resolutions, due triggers, queued imports, health (§6.7)."""
    root: Path = ctx.obj["root"]
    ledger = Ledger(root)
    now = _now()

    forecasts = ledger.all_forecasts()
    due_res = due_forecasts(ledger, _questions_dir(root), now)
    due_trigs = due_triggers(ledger, now)
    queued = _queued_imports(root, ledger)

    click.echo(f"Ledger: {len(forecasts)} forecast(s)")
    if not forecasts:
        click.echo("Empty ledger.")

    click.echo(f"Due resolutions: {len(due_res)}")
    for fid in due_res:
        click.echo(f"  - {fid}")

    click.echo(f"Due triggers: {len(due_trigs)}")
    for fid, trig in due_trigs:
        click.echo(f"  - {fid}: {trig.check}")

    click.echo(f"Queued imports (unforecast): {len(queued)}")
    for qid in queued:
        click.echo(f"  - {qid}")

    if any(_load_spec(root, r.question_id) and _load_spec(root, r.question_id).blind
           for r in forecasts):
        click.echo("NOTE: this ledger contains blind questions (§5.13).")

    if due_res or due_trigs or queued:
        ctx.exit(_ATTENTION)


# --------------------------------------------------------------------------- #
# question create
# --------------------------------------------------------------------------- #
@cli.group()
def question() -> None:
    """Question-spec management."""


@question.command("create")
@click.argument("spec_path", type=click.Path(exists=True, dir_okay=False))
@click.pass_context
def question_create(ctx: click.Context, spec_path: str) -> None:
    """Validate a QuestionSpec JSON, stamp its id/created_at, and store it."""
    root: Path = ctx.obj["root"]
    raw = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    now = _now()
    # The CLI assigns the id and creation time — never the caller (§5.9).
    raw["id"] = new_question_id(now, _next_question_seq(root, now))
    raw["created_at"] = now.isoformat()
    try:
        spec = QuestionSpec.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError et al.
        raise click.ClickException(f"invalid question spec: {exc}") from exc

    d = _questions_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{spec.id}.json"
    if path.exists():
        raise click.ClickException(f"question {spec.id} already exists")
    path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    click.echo(f"Created {spec.id} at {path}")


# --------------------------------------------------------------------------- #
# commit
# --------------------------------------------------------------------------- #
@cli.command()
@click.argument("forecast_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True, help="Validate and print, but do not write.")
@click.pass_context
def commit(ctx: click.Context, forecast_path: str, dry_run: bool) -> None:
    """Validate, stamp, and append a ForecastRecord to the ledger/stream (§5.9)."""
    root: Path = ctx.obj["root"]
    ledger = Ledger(root)
    now = _now()

    raw = json.loads(Path(forecast_path).read_text(encoding="utf-8"))
    qid = raw.get("question_id")
    if not qid:
        raise click.ClickException("forecast is missing 'question_id'")

    # Probability floor/ceiling (§5.9 step 2).
    if "probability" not in raw:
        raise click.ClickException("forecast is missing 'probability'")
    raw["probability"] = min(max(float(raw["probability"]), _PROB_FLOOR), _PROB_CEIL)

    # Mandatory update triggers (§5.9 step 4): >= 1, or >= 3 if fragile.
    resilience = raw.get("resilience")
    triggers = raw.get("update_triggers") or []
    required = 3 if resilience == "fragile" else 1
    if len(triggers) < required:
        raise click.ClickException(
            f"resilience={resilience!r} requires >= {required} update trigger(s); "
            f"got {len(triggers)}"
        )

    # Stream position: an initial forecast opens a stream; updates append.
    stream = ledger.stream(qid)
    fid = new_forecast_id(now, ledger.next_seq("F", now))
    if stream:
        raw["stream_id"] = stream[0].stream_id
        raw["stream_seq"] = max(r.stream_seq for r in stream) + 1
    else:
        raw["stream_id"] = fid
        raw["stream_seq"] = 0

    # CLI-stamped provenance overrides anything the caller supplied (§5.9).
    raw["id"] = fid
    raw["committed_at"] = now.isoformat()
    raw["git_sha"] = _git_sha()

    try:
        rec = ForecastRecord.model_validate(raw)
    except Exception as exc:
        raise click.ClickException(f"invalid forecast: {exc}") from exc

    if dry_run:
        click.echo("[dry-run] forecast validated and stamped (not written):")
        click.echo(rec.model_dump_json(indent=2))
        return

    path = ledger.append_forecast(rec)
    click.echo(
        f"Committed {rec.id} (stream {rec.stream_id} seq {rec.stream_seq}) -> {path}"
    )

    # Import questions: unseal the crowd price into the `market` baseline (§5.13).
    spec = _load_spec(root, qid)
    if spec is not None and spec.origin == "import":
        try:
            price = unseal_market_baseline(root, qid)
            if price is None:
                click.echo(
                    f"No market baseline for {qid}: community prediction unavailable at seal time."
                )
            else:
                record_baseline(root, qid, "market", price)
                click.echo(f"Unsealed market baseline for {qid}: {price:.4f}")
        except Exception as exc:  # missing/tampered snapshot must not lose the commit
            click.echo(
                f"warning: could not unseal market baseline for {qid}: {exc}",
                err=True,
            )

    # Guard: every forecast should carry a naive-claude baseline, elicited before
    # research (§9.2). Warn (don't block) so the miss can't slip by silently.
    if "naive-claude" not in get_baselines(root, qid):
        click.echo(
            f"warning: no naive-claude baseline recorded for {qid} — run "
            f"`oracle baseline record {qid} naive-claude <p>` (§9.2).",
            err=True,
        )


# --------------------------------------------------------------------------- #
# triggers
# --------------------------------------------------------------------------- #
@cli.group()
def triggers() -> None:
    """Update-trigger registry (§5.14)."""


@triggers.command("due")
@click.pass_context
def triggers_due(ctx: click.Context) -> None:
    """List update triggers whose due moment has arrived; exit 10 if any."""
    root: Path = ctx.obj["root"]
    ledger = Ledger(root)
    due = due_triggers(ledger, _now())
    if not due:
        click.echo("No triggers due.")
        return
    for fid, trig in due:
        when = trig.due.isoformat() if trig.due else ""
        click.echo(f"{fid}\t{trig.type}\t{trig.check}\t{when}")
    ctx.exit(_ATTENTION)


@triggers.command("check")
@click.argument("qid")
@click.pass_context
def triggers_check(ctx: click.Context, qid: str) -> None:
    """Show the update triggers registered on a question's latest forecast."""
    root: Path = ctx.obj["root"]
    stream = Ledger(root).stream(qid)
    if not stream:
        raise click.ClickException(f"no forecasts for question {qid!r}")
    latest = stream[-1]
    if not latest.update_triggers:
        click.echo("No triggers registered.")
        return
    for trig in latest.update_triggers:
        when = trig.due.isoformat() if trig.due else "(unscheduled)"
        click.echo(f"{trig.type}\t{trig.check}\t{when}")


# --------------------------------------------------------------------------- #
# stream
# --------------------------------------------------------------------------- #
@cli.group("stream")
def stream_grp() -> None:
    """Per-question forecast streams."""


@stream_grp.command("show")
@click.argument("qid")
@click.pass_context
def stream_show(ctx: click.Context, qid: str) -> None:
    """Print the probability time series for a question."""
    root: Path = ctx.obj["root"]
    recs = Ledger(root).stream(qid)
    if not recs:
        raise click.ClickException(f"no forecasts for question {qid!r}")
    for r in recs:
        click.echo(
            f"seq {r.stream_seq}\t{r.probability:.4f}\t"
            f"{r.committed_at.isoformat()}\t{r.id}"
        )


# --------------------------------------------------------------------------- #
# baseline
# --------------------------------------------------------------------------- #
@cli.group()
def baseline() -> None:
    """Baseline (benchmark) store."""


@baseline.command("record")
@click.argument("qid")
@click.argument("name")
@click.argument("p", type=float)
@click.pass_context
def baseline_record(ctx: click.Context, qid: str, name: str, p: float) -> None:
    """Record a baseline forecast (e.g. naive-claude, base-rate-only)."""
    root: Path = ctx.obj["root"]
    path = record_baseline(root, qid, name, p)
    click.echo(f"Recorded baseline {name}={p} for {qid} -> {path}")


# --------------------------------------------------------------------------- #
# resolve
# --------------------------------------------------------------------------- #
@cli.command()
@click.argument("fid", required=False)
@click.option("--outcome", type=click.Choice(["yes", "no", "void"]))
@click.option("--evidence", default="")
@click.option("--due", "due_mode", is_flag=True, help="List due resolutions; exit 10 if any.")
@click.option("--platform-only", is_flag=True, help="Cron mode: only platform-resolvable imports.")
@click.option("--kelly-fraction", type=float, default=0.25)
@click.pass_context
def resolve(
    ctx: click.Context,
    fid: str | None,
    outcome: str | None,
    evidence: str,
    due_mode: bool,
    platform_only: bool,
    kelly_fraction: float,
) -> None:
    """Resolve a forecast (``<fid> --outcome ...``) or list what is due (``--due``)."""
    root: Path = ctx.obj["root"]
    ledger = Ledger(root)
    now = _now()

    if due_mode:
        due = due_forecasts(ledger, _questions_dir(root), now)
        if platform_only:
            # Auto-resolve import questions by reading the platform's settled
            # outcome (Manifold/Polymarket/Metaculus). Only resolve when the
            # platform has definitively settled; leave everything else pending.
            conns = registry()
            resolved_now: list[str] = []
            pending: list[str] = []
            for f in due:
                spec = _load_spec(root, ledger.get_forecast(f).question_id)
                if spec is None or spec.origin != "import" or not spec.linked_markets:
                    continue  # not platform-resolvable; leave for a human/LLM session
                link = spec.linked_markets[0]
                conn = conns.get(link.platform)
                get_res = getattr(conn, "get_resolution", None) if conn else None
                if get_res is None:
                    pending.append(f)
                    continue
                try:
                    oc = get_res(link.market_id)
                except Exception as exc:  # noqa: BLE001 — a read failure must not crash cron
                    click.echo(f"warning: could not read resolution for {f}: {exc}", err=True)
                    pending.append(f)
                    continue
                if oc is None:
                    pending.append(f)  # platform has not settled the market yet
                    continue
                rec = build_resolution(
                    ledger, root, f, oc,
                    f"auto-resolved from {link.platform} market {link.market_id}",
                    now, kelly_fraction=kelly_fraction,
                )
                ledger.append_resolution(rec)
                resolved_now.append(f)
                click.echo(f"Auto-resolved {f} -> {oc} (via {link.platform})")
            for f in pending:
                click.echo(f"pending (not yet settled on-platform): {f}")
            if not resolved_now and not pending:
                click.echo("Nothing due.")
                return
            if pending:
                ctx.exit(_ATTENTION)
            return
        # Interactive --due: list everything due (incl. bespoke) for a human/LLM.
        if not due:
            click.echo("Nothing due.")
            return
        for f in due:
            click.echo(f)
        ctx.exit(_ATTENTION)

    if not fid:
        raise click.ClickException("provide a forecast id, or use --due")
    if not outcome:
        raise click.ClickException("--outcome is required (yes|no|void)")

    try:
        rec = build_resolution(
            ledger, root, fid, outcome, evidence, now, kelly_fraction=kelly_fraction
        )
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    path = ledger.append_resolution(rec)
    click.echo(f"Resolved {fid} -> {outcome} ({path})")
    for name, value in rec.scores.items():
        click.echo(f"  {name}: {value:.4f}")


# --------------------------------------------------------------------------- #
# aggregate
# --------------------------------------------------------------------------- #
@cli.command()
@click.option("--probs", required=True, help="Comma-separated probabilities, e.g. 0.6,0.7,0.55")
@click.option("--market", type=float, default=None, help="Optional market price to fold in.")
@click.option("--market-weight", type=float, default=1.0)
@click.option("--method", type=click.Choice(["median", "trimmed", "geo_odds"]), default=None)
def aggregate(
    probs: str, market: float | None, market_weight: float, method: str | None
) -> None:
    """Pool probabilities (median / trimmed / geo-odds); optionally fold in a market."""
    ps = [float(x) for x in probs.split(",") if x.strip()]
    methods = [method] if method else ["median", "trimmed", "geo_odds"]
    for m in methods:
        value = pool(ps, m, market_price=market, market_weight=market_weight)
        click.echo(f"{m}: {value:.4f}")


# --------------------------------------------------------------------------- #
# import
# --------------------------------------------------------------------------- #
@cli.group("import")
def import_grp() -> None:
    """Blind import of external market questions (§5.13)."""


def _approve_candidates(root: Path, cands: list) -> list[str]:
    conns = registry()
    now = _now()
    created: list[str] = []
    for c in cands:
        conn = conns.get(c.platform)
        if conn is None:
            continue
        try:
            snap = conn.fetch_snapshot(c.market_id)
            if snap.price is None:
                # No community/market price to seal -> no untainted Oracle-vs-market
                # benchmark is possible, so don't import it (§9.3 / user policy).
                click.echo(
                    f"skipping {c.platform}:{c.market_id} — no market price available "
                    f"(cannot benchmark)"
                )
                continue
            seal(root, c, snap)
            spec = candidate_to_spec(c, now, _next_question_seq(root, now))
            d = _questions_dir(root)
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{spec.id}.json").write_text(
                spec.model_dump_json(indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 — one bad candidate must not abort the batch
            click.echo(
                f"warning: skipping {c.platform}:{c.market_id} "
                f"({type(exc).__name__}: {exc})",
                err=True,
            )
            continue
        created.append(spec.id)
        click.echo(f"Approved {c.platform}:{c.market_id} -> {spec.id}")
    return created


@import_grp.command("fetch")
@click.option("--platform", default="manifold,metaculus")
@click.option("--closes-within", "closes_within", default="14d")
@click.option("--max", "max_n", type=int, default=20)
@click.option("--min-traders", type=int, default=30)
@click.option("--min-forecasters", type=int, default=20)
@click.option("--auto-approve", is_flag=True, help="Seal + create specs immediately (cron).")
@click.pass_context
def import_fetch(
    ctx: click.Context,
    platform: str,
    closes_within: str,
    max_n: int,
    min_traders: int,
    min_forecasters: int,
    auto_approve: bool,
) -> None:
    """Fetch soon-closing candidates through the blind filter pipeline."""
    root: Path = ctx.obj["root"]
    platforms = [p.strip() for p in platform.split(",") if p.strip()]
    filters = {"min_traders": min_traders, "min_forecasters": min_forecasters}
    cands = fetch_and_filter(
        _parse_days(closes_within), platforms, filters, _questions_dir(root)
    )[:max_n]
    if not cands:
        click.echo("No candidates found.")
        return
    for c in cands:
        click.echo(f"{c.platform}\t{c.market_id}\t{c.title}")
    if auto_approve:
        _approve_candidates(root, cands)


@import_grp.command("approve")
@click.argument("candidate_ids", nargs=-1)
@click.option("--all", "approve_all", is_flag=True)
@click.option("--platform", default="manifold,metaculus")
@click.option("--closes-within", "closes_within", default="14d")
@click.option("--min-traders", "min_traders", default=None, type=int)
@click.option("--min-forecasters", "min_forecasters", default=None, type=int)
@click.pass_context
def import_approve(
    ctx: click.Context,
    candidate_ids: tuple[str, ...],
    approve_all: bool,
    platform: str,
    closes_within: str,
    min_traders: int | None,
    min_forecasters: int | None,
) -> None:
    """Create specs + seal snapshots for approved candidates (re-fetches to resolve ids)."""
    root: Path = ctx.obj["root"]
    platforms = [p.strip() for p in platform.split(",") if p.strip()]
    # Honor the same quality thresholds as `fetch` so the requested ids resurface.
    filters: dict = {}
    if min_traders is not None:
        filters["min_traders"] = min_traders
    if min_forecasters is not None:
        filters["min_forecasters"] = min_forecasters
    cands = fetch_and_filter(
        _parse_days(closes_within), platforms, filters, _questions_dir(root)
    )
    if not approve_all:
        wanted = set(candidate_ids)
        cands = [c for c in cands if c.market_id in wanted]
    if not cands:
        click.echo("No matching candidates to approve.")
        return
    _approve_candidates(root, cands)


@import_grp.command("queue")
@click.pass_context
def import_queue(ctx: click.Context) -> None:
    """List queued, unforecast import questions."""
    root: Path = ctx.obj["root"]
    queued = _queued_imports(root, Ledger(root))
    if not queued:
        click.echo("No queued imports.")
        return
    for qid in queued:
        click.echo(qid)


# --------------------------------------------------------------------------- #
# scoreboard / pnl
# --------------------------------------------------------------------------- #
@cli.command()
@click.option("--segment", default=None)
@click.option("--baseline", "baseline_name", default=None, help="Accepted for compatibility; all baselines are shown.")
@click.option("--render", is_flag=True, help="Also write reports/scoreboard.md.")
@click.pass_context
def scoreboard(
    ctx: click.Context, segment: str | None, baseline_name: str | None, render: bool
) -> None:
    """Render the accuracy scoreboard (§9.4)."""
    root: Path = ctx.obj["root"]
    md = render_scoreboard(Ledger(root), root, segment=segment)
    if render:
        out = root / "reports" / "scoreboard.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        click.echo(f"Wrote {out}")
    click.echo(md)


@cli.command()
@click.option("--kelly-fraction", type=float, default=0.25)
@click.option("--render", is_flag=True, help="Also write reports/pnl.md.")
@click.pass_context
def pnl(ctx: click.Context, kelly_fraction: float, render: bool) -> None:
    """Render the paper-trading P&L track vs the market baseline (§9.4)."""
    root: Path = ctx.obj["root"]
    md = render_pnl(Ledger(root), root, kelly_fraction=kelly_fraction)
    if render:
        out = root / "reports" / "pnl.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        click.echo(f"Wrote {out}")
    click.echo(md)


# --------------------------------------------------------------------------- #
# calibration
# --------------------------------------------------------------------------- #
@cli.group()
def calibration() -> None:
    """Recalibration-map fitting and selection (§9.5)."""


def _resolved_pairs(ledger: Ledger) -> list[tuple[float, int]]:
    pairs: list[tuple[float, int]] = []
    for rec in ledger.all_forecasts():
        res = ledger.resolution_for(rec.id)
        if res is None or res.outcome == "void":
            continue
        pairs.append((rec.probability, 1 if res.outcome == "yes" else 0))
    return pairs


@calibration.command("fit")
@click.pass_context
def calibration_fit(ctx: click.Context) -> None:
    """Fit + LOO-select a recalibration map on resolved forecasts (needs N>=50)."""
    root: Path = ctx.obj["root"]
    pairs = _resolved_pairs(Ledger(root))
    try:
        m = fit_recalibration(pairs)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    path = save_map(m, _calibration_dir(root))
    click.echo(
        f"Fitted {m.id} (kind={m.kind}, n={m.fitted_on_n}, "
        f"LOO Brier {m.loo_brier_before:.4f} -> {m.loo_brier_after:.4f}) -> {path}"
    )


@calibration.command("show")
@click.pass_context
def calibration_show(ctx: click.Context) -> None:
    """Show the active recalibration map, if any."""
    root: Path = ctx.obj["root"]
    m = load_active_map(_calibration_dir(root))
    if m is None:
        click.echo("No active calibration map.")
        return
    click.echo(m.model_dump_json(indent=2))


@calibration.command("activate")
@click.argument("map_id")
@click.pass_context
def calibration_activate(ctx: click.Context, map_id: str) -> None:
    """Confirm a calibration map exists (the newest map is the active one)."""
    root: Path = ctx.obj["root"]
    path = _calibration_dir(root) / f"{map_id}.json"
    if not path.exists():
        raise click.ClickException(f"no calibration map {map_id!r}")
    click.echo(
        f"{map_id} exists. The active map is the most recently created one; "
        "re-fit to activate a newer map."
    )


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
@cli.command()
@click.argument("fid")
@click.pass_context
def report(ctx: click.Context, fid: str) -> None:
    """Render reports/<fid>.md for a committed forecast (§5.10)."""
    root: Path = ctx.obj["root"]
    ledger = Ledger(root)
    try:
        rec = ledger.get_forecast(fid)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    spec = _load_spec(root, rec.question_id)
    if spec is None:
        raise click.ClickException(f"no question spec for {rec.question_id!r}")
    baselines = get_baselines(root, rec.question_id)
    stream = ledger.stream(rec.question_id)
    # Embed the evidence log verbatim so the report is self-contained (no links).
    evidence_body = ""
    if rec.evidence_log:
        ev_path = root / rec.evidence_log
        if ev_path.is_file():
            evidence_body = ev_path.read_text(encoding="utf-8")
    md = render_report(rec, spec, baselines, stream, evidence_body=evidence_body)
    out = root / "reports" / f"{fid}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    click.echo(f"Wrote {out}")


# --------------------------------------------------------------------------- #
# connectors
# --------------------------------------------------------------------------- #
@cli.command()
@click.option("--open", "open_", is_flag=True, help="Open the generated site in a browser.")
@click.pass_context
def site(ctx: click.Context, open_: bool) -> None:
    """Render the static HTML site (ledger + per-question pages) into <root>/site."""
    # Imported lazily so `import oracle.cli` does not require jinja/markdown here.
    from oracle.site import render_site

    root: Path = ctx.obj["root"]
    out = render_site(root)
    index = out / "index.html"
    click.echo(f"Wrote {index}")
    if open_:
        import webbrowser

        webbrowser.open(index.resolve().as_uri())


# --------------------------------------------------------------------------- #
# connectors
# --------------------------------------------------------------------------- #
@cli.group()
def connectors() -> None:
    """External data/market connectors."""


@connectors.command("doctor")
def connectors_doctor() -> None:
    """Report connector availability without printing any secret values (§10.5)."""
    for name, available, detail in doctor():
        click.echo(f"{name}\t{'OK' if available else 'unavailable'}\t{detail}")


main = cli


if __name__ == "__main__":  # pragma: no cover
    main()
