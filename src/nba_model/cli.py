"""nba_model CLI — prepare / walkforward / publish.

Exit codes (mirrors scripts/fetch_nba.py conventions):
  0  ok
  2  missing/unrejected API key (fail-closed, nothing written)
  3  balldontlie tier lacks box scores (nbacom path never hits this)
  4  rate limit exhausted
  5  network / protocol / no-data error
  6  bad arguments
  10 publish refused by gates (a refusal artifact was written)

USAGE:
  python3 src/nba_model/cli.py prepare --provider synthetic
  python3 src/nba_model/cli.py walkforward --provider synthetic \
      --start 2026-11-01 --end 2026-11-17
  python3 src/nba_model/cli.py publish --provider synthetic --date 2026-11-17

All three commands are fully offline with --provider synthetic
(labeled research fixtures). --provider nbacom is the FREE production
path: official stats.nba.com league feeds, keyless (DECISIONS.md D7).
--provider bdl is the licensed paid alternative (BALLDONTLIE_API_KEY,
ALL-STAR tier or higher for box scores); --provider fixtures reads the
committed viewer fixture files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # run as a plain script: python3 src/nba_model/cli.py
    _SRC = str(Path(__file__).resolve().parents[1])  # .../src
    if _SRC not in sys.path:
        sys.path.insert(0, _SRC)

import pandas as pd  # noqa: E402

from nba_model import config  # noqa: E402
from nba_model.data.dataset import build_dataset  # noqa: E402
from nba_model.data.nbacom import NbaComProvider  # noqa: E402
from nba_model.data.providers import (  # noqa: E402
    BalldontlieProvider,
    FixtureProvider,
    MissingKeyError,
    ProviderNetworkError,
    RateLimitError,
    SyntheticSeasonProvider,
    TierError,
)
from nba_model.eval.walkforward import run_walk_forward  # noqa: E402
from nba_model.model.projector import NBAPointsProjector  # noqa: E402
from nba_model.publish.board import build_board, publish_board  # noqa: E402
from nba_model.publish.gates import evaluate_freshness_gate  # noqa: E402

EXIT_OK, EXIT_NO_KEY, EXIT_TIER, EXIT_RATE, EXIT_NETWORK, EXIT_ARGS, EXIT_REFUSED = 0, 2, 3, 4, 5, 6, 10


def _default_out() -> Path:
    return Path(__file__).resolve().parent / "out"


def build_provider(args):
    if args.provider == "nbacom":
        return NbaComProvider()  # free, keyless (DECISIONS.md D7)
    if args.provider == "bdl":
        return BalldontlieProvider()
    if args.provider == "fixtures":
        root = Path(__file__).resolve().parents[3]  # repo root (src/nba_model/cli.py)
        return FixtureProvider(
            games_file=str(root / "viewer" / f"nba_games_{args.date}.json") if args.date
            else str(root / "viewer" / "nba_games_2026-10-22.json"),
            boxscore_file=None,
        )
    if args.provider == "synthetic":
        start = args.start or "2026-10-19"
        return SyntheticSeasonProvider(start_date=start, n_days=args.days or 45)
    raise ValueError(f"unknown provider: {args.provider}")


def load_world(args) -> dict:
    """provider -> normalized rows/games (+odds+injuries when available)."""
    provider = build_provider(args)
    if args.provider in ("bdl", "nbacom"):
        dates = pd.date_range(args.start, args.end or args.start, freq="D")
        world = provider.fetch_range([d.date().isoformat() for d in dates])
        world.setdefault("odds", [])
        world.setdefault("injuries", [])
    else:
        world = provider.fetch_range(None)
    return world


def cmd_prepare(args) -> int:
    world = load_world(args)
    df, meta = build_dataset(world["rows"], world["games"])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    meta_path = out / "nba_dataset_meta.json"
    meta_path.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    try:
        data_path = out / "nba_player_games.parquet"
        df.to_parquet(data_path, index=False)
    except ImportError:
        data_path = out / "nba_player_games.csv"  # pyarrow absent — CSV fallback
        df.to_csv(data_path, index=False)
    odds_path = out / "nba_odds_feed.json"
    odds_path.write_text(json.dumps(world.get("odds", []), indent=1) + "\n", encoding="utf-8")
    print(f"dataset: {meta['n_rows']} player-games, {meta['n_games']} games, "
          f"{meta['n_players']} players [{meta['min_game_date']} .. {meta['max_game_date']}]")
    print(f"source={meta['source']} all_fixture={meta['all_fixture']}")
    print(f"wrote {data_path}\nwrote {meta_path}\nwrote {odds_path}")
    return EXIT_OK


def cmd_walkforward(args) -> int:
    world = load_world(args)
    df, meta = build_dataset(world["rows"], world["games"])
    result = run_walk_forward(
        df, args.start, args.end,
        odds=world.get("odds"), injuries=world.get("injuries"),
    )
    summary = {
        "window": [args.start, args.end],
        "summary": result.summary,
        "distributional": result.distributional,
        "uncalibrated": result.uncalibrated,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "nba_walkforward_summary.json"
    path.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    result.records.to_csv(out / "nba_walkforward_records.csv", index=False)

    print(f"window {args.start}..{args.end}")
    dist = result.distributional
    print(f"distributional: n={dist.get('n_player_games')} z_mean={dist.get('z_mean')} "
          f"z_sd={dist.get('z_sd')}  (z_sd≈1.0 => variance honest)")
    s = result.summary
    print(f"line records: n={s.get('n')} slope={s.get('calibration_slope')} "
          f"brier_model={s.get('brier_model')} brier_market={s.get('brier_market')} "
          f"brier_naive={s.get('brier_naive')}")
    if s.get("brier_vs_market") is not None:
        ahead = "MODEL ahead of market" if s["brier_vs_market"] < 0 else "market ahead (reported, not hidden)"
        print(f"brier_vs_market={s['brier_vs_market']:+.5f}  [{ahead}]")
    print(f"uncalibrated={result.uncalibrated}")
    print(f"wrote {path}")
    return EXIT_OK


def cmd_publish(args) -> int:
    world = load_world(args)
    df, meta = build_dataset(world["rows"], world["games"])
    slate = args.date or meta["max_game_date"]
    if slate not in set(df["game_date"].dropna()):
        print(f"ERROR: slate date {slate} has no games in the dataset", file=sys.stderr)
        return EXIT_ARGS

    # Calibration summary from walk-forward strictly BEFORE the slate.
    dates = sorted(df["game_date"].dropna().unique())
    wf_start = dates[max(0, min(len(dates) - 1, 12))]
    wf_end = dates[dates.index(slate) - 1] if dates.index(slate) > 0 else None
    if wf_end and wf_end > wf_start:
        result = run_walk_forward(df, wf_start, wf_end,
                                  odds=world.get("odds"), injuries=world.get("injuries"))
        wf_summary = result.summary
    else:
        wf_summary = {"n": 0, "uncalibrated": True, "reason": "insufficient pre-slate history"}

    from nba_model.features.form import add_rolling_form
    from nba_model.features.injuries import add_availability_adjustments
    full = add_rolling_form(df)
    train = full[full["game_date"] < slate]
    test = full[(full["game_date"] == slate) & (~full["dnp"])].copy()
    if test.empty:
        print(f"ERROR: no played rows for slate {slate}", file=sys.stderr)
        return EXIT_NETWORK
    test = add_availability_adjustments(test, world.get("injuries"))
    preds = NBAPointsProjector().fit(train).predict(test, history=train)

    slate_odds = [q for q in (world.get("odds") or [])
                  if str(q.get("observed_at", "")).startswith(slate)]
    now = pd.Timestamp(args.as_of) if args.as_of else None
    board = build_board(preds, slate_odds, wf_summary, meta, now=now)
    board_path, sha = publish_board(board, args.out)

    print(f"slate {slate}: status={board['status']}")
    if board["status"] == "REFUSED":
        for reason in board["reasons"]:
            print(f"  GATE FAIL: {reason}")
        print(f"wrote refusal artifact {board_path}")
        print(f"receipt sha256={sha}")
        return EXIT_REFUSED
    print(f"plays published: {len(board['payload']['plays'])} / {config.BOARD_SIZE} "
          f"(candidates={board['payload']['n_candidates']})")
    for p in board["payload"]["plays"]:
        print(f"  {p['player_name']:<12} {p['side']:<5} {p['line']:>5} "
              f"edge={p['edge']:+.3f} model={p['model_p']:.3f} "
              f"mkt={p['market_p_devig']:.3f} books={p['n_books']}")
    print(f"brier_vs_market (reported): {board['payload']['walk_forward']['brier_vs_market']}")
    print(f"wrote {board_path}")
    print(f"receipt sha256={sha}")
    return EXIT_OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="nba_model", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(_default_out()), help="output directory")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--provider", choices=["synthetic", "bdl", "nbacom", "fixtures"],
                       default="synthetic")
        p.add_argument("--start", help="window start (YYYY-MM-DD)")
        p.add_argument("--end", help="window end (YYYY-MM-DD)")
        p.add_argument("--date", help="slate date (YYYY-MM-DD)")
        p.add_argument("--days", type=int, default=45, help="synthetic season length")
        p.add_argument("--as-of", help="freeze 'now' for offline demos (ISO datetime)")

    for name, fn in (("prepare", cmd_prepare), ("walkforward", cmd_walkforward), ("publish", cmd_publish)):
        p = sub.add_parser(name)
        common(p)
        p.set_defaults(fn=fn)

    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except MissingKeyError as exc:
        print(f"GATE: {exc} The viewer keeps research fixtures.", file=sys.stderr)
        return EXIT_NO_KEY
    except TierError as exc:
        print(f"GATE: {exc}", file=sys.stderr)
        return EXIT_TIER
    except RateLimitError as exc:
        print(f"GATE: {exc}", file=sys.stderr)
        return EXIT_RATE
    except (ProviderNetworkError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_NETWORK


if __name__ == "__main__":
    sys.exit(main())
