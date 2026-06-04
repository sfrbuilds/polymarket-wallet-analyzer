#!/usr/bin/env python3
"""
Polymarket Wallet Analyzer
Pull complete trade history, positions, and P&L for any Polymarket wallet.
Handles pagination automatically, exports to CSV, and prints a summary.

No API key required. All endpoints are public.

SETUP
-----
  pip install requests
  python3 wallet_analyzer.py --help

TYPICAL WORKFLOW
----------------
  Step 1: Browse the leaderboard to find interesting wallets

    python3 wallet_analyzer.py --leaderboard
    python3 wallet_analyzer.py --leaderboard --period WEEK --category POLITICS
    python3 wallet_analyzer.py --leaderboard --period ALL --order-by VOL --limit 100

  Step 2: Copy a wallet address from the printed table, then analyze it

    python3 wallet_analyzer.py --wallet 0xABC123...

  Or combine: pull leaderboard and immediately analyze the top N wallets

    python3 wallet_analyzer.py --leaderboard --analyze-top 5

OTHER USAGE
-----------
  # Multiple specific wallets in one run
  python3 wallet_analyzer.py --wallet 0xABC 0xDEF 0xGHI

  # Load wallets from a text file (one address per line)
  python3 wallet_analyzer.py --wallet-file my_wallets.txt

  # Only trades since a specific date
  python3 wallet_analyzer.py --wallet 0xABC --since 2025-01-01

  # Save raw JSON alongside CSV
  python3 wallet_analyzer.py --wallet 0xABC --json

  # Top holders for a specific market
  python3 wallet_analyzer.py --market 0xCONDITION_ID

LEADERBOARD OPTIONS
-------------------
  --period      DAY | WEEK | MONTH | ALL  (default: WEEK)
  --category    OVERALL | POLITICS | SPORTS | CRYPTO | CULTURE |
                ECONOMICS | TECH | FINANCE | WEATHER | MENTIONS  (default: OVERALL)
  --order-by    PNL | VOL  (default: PNL)
  --limit       1-1000  (default: 50)
  --analyze-top N  also run full wallet analysis on the top N from the leaderboard

HOW TO FIND A WALLET ADDRESS
-----------------------------
  Polymarket.com profile URL: polymarket.com/profile/0x...
  The 0x address in the URL is the proxy wallet to use here.
  The leaderboard (--leaderboard) is the easiest way to discover wallets.

OUTPUT FILES  (written to ./output/)
-------------------------------------
  {wallet}_trades.csv      All filled trades (paginated, full history)
  {wallet}_positions.csv   Open positions
  {wallet}_closed.csv      Closed/resolved positions
  {wallet}_activity.csv    All on-chain events
  {wallet}_summary.txt     P&L summary, win rate, top markets
  leaderboard_{cat}_{period}.csv   Top traders from the leaderboard
"""

import argparse, csv, json, os, sys, time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, List, Optional
import requests

# ── API bases ──────────────────────────────────────────────────────────────────
DATA = "https://data-api.polymarket.com"

# Official leaderboard endpoint (docs.polymarket.com/api-reference/core/get-trader-leaderboard-rankings)
LEADERBOARD_URL = f"{DATA}/v1/leaderboard"

HEADERS = {"Accept": "application/json"}
DELAY   = 0.3    # seconds between requests
PAGE    = 500    # records per page for history pagination
OUT_DIR = "output"

VALID_PERIODS    = {"DAY", "WEEK", "MONTH", "ALL"}
VALID_CATEGORIES = {
    "OVERALL", "POLITICS", "SPORTS", "CRYPTO", "CULTURE",
    "ECONOMICS", "TECH", "FINANCE", "WEATHER", "MENTIONS",
}
VALID_ORDER_BY = {"PNL", "VOL"}


# ==============================================================================
# HTTP helpers
# ==============================================================================

def _get(url: str, params: dict = None, retries: int = 3) -> Optional[Any]:
    """GET with retry and polite delay."""
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = 2 ** attempt
                print(f"    Rate limited - waiting {wait}s...")
                time.sleep(wait)
                continue
            print(f"    HTTP {r.status_code}  {url}")
            return None
        except requests.exceptions.Timeout:
            print(f"    Timeout (attempt {attempt+1}/{retries})  {url}")
        except Exception as e:
            print(f"    ERR  {url}: {e}")
            return None
    return None


# ==============================================================================
# Pagination engine
# ==============================================================================

def _paginate(endpoint: str, user: str, since_ts: Optional[int] = None,
              extra_params: dict = None) -> List[dict]:
    """
    Fetch ALL records from a data-api endpoint using offset pagination.
    Stops when a page returns fewer than PAGE records or since_ts is crossed.
    """
    url      = f"{DATA}{endpoint}"
    records  = []
    offset   = 0
    page_num = 0

    while True:
        page_num += 1
        params = {"user": user, "limit": PAGE, "offset": offset}
        if extra_params:
            params.update(extra_params)

        data = _get(url, params=params)
        time.sleep(DELAY)

        if data is None:
            break

        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = (data.get("data") or data.get("trades") or data.get("positions")
                    or data.get("activity") or data.get("events") or [])
        else:
            rows = []

        if not rows:
            break

        if since_ts:
            filtered = []
            stop_early = False
            for r in rows:
                ts_val = r.get("timestamp") or r.get("createdAt") or r.get("matchedAt") or 0
                try:
                    ts_int = int(float(ts_val))
                    if ts_int > 1e12:
                        ts_int //= 1000
                    if ts_int >= since_ts:
                        filtered.append(r)
                    else:
                        stop_early = True
                except (TypeError, ValueError):
                    filtered.append(r)
            rows = filtered
            if stop_early:
                records.extend(rows)
                break

        records.extend(rows)
        print(f"    Page {page_num}: {len(rows)} records  (total: {len(records)})", end="\r")

        if len(rows) < PAGE:
            break

        offset += PAGE

    if page_num > 1:
        print()

    return records


# ==============================================================================
# Data normalisation
# ==============================================================================

def _norm_ts(val) -> str:
    if not val:
        return ""
    try:
        n = float(val)
        if n > 1e12:
            n /= 1000
        return datetime.fromtimestamp(n, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(val)


def _norm_price(val) -> str:
    try:
        f = float(val)
        if 0 <= f <= 1:
            return f"{f * 100:.2f}"
        return f"{f:.4f}"
    except (TypeError, ValueError):
        return str(val) if val else ""


def _safe(val, fallback="") -> str:
    if val is None:
        return fallback
    return str(val)


def _norm_trade(t: dict) -> dict:
    return {
        "timestamp":    _norm_ts(t.get("timestamp") or t.get("createdAt") or t.get("matchedAt")),
        "market":       _safe(t.get("title") or t.get("market") or t.get("conditionId")),
        "condition_id": _safe(t.get("conditionId") or t.get("condition_id")),
        "outcome":      _safe(t.get("outcome") or t.get("side") or t.get("takerSide")),
        "price_cents":  _norm_price(t.get("price")),
        "size":         _safe(t.get("size") or t.get("shares") or t.get("amount")),
        "notional_usd": _safe(t.get("usdcSize") or t.get("notional") or t.get("value")),
        "type":         _safe(t.get("type") or t.get("action")),
        "tx_hash":      _safe(t.get("transactionHash") or t.get("txHash")),
    }


def _norm_position(p: dict, kind: str = "open") -> dict:
    return {
        "kind":          kind,
        "market":        _safe(p.get("title") or p.get("market") or p.get("conditionId")),
        "condition_id":  _safe(p.get("conditionId") or p.get("condition_id")),
        "outcome":       _safe(p.get("outcome") or p.get("side")),
        "size":          _safe(p.get("size") or p.get("shares")),
        "avg_price":     _norm_price(p.get("avgPrice") or p.get("averagePrice")),
        "current_value": _safe(p.get("currentValue") or p.get("value")),
        "pnl":           _safe(p.get("cashPnl") or p.get("pnl") or p.get("realizedPnl")),
        "status":        _safe(p.get("status") or p.get("resolution")),
    }


def _norm_activity(a: dict) -> dict:
    return {
        "timestamp":    _norm_ts(a.get("timestamp") or a.get("createdAt")),
        "type":         _safe(a.get("type") or a.get("action")),
        "market":       _safe(a.get("title") or a.get("market") or a.get("conditionId")),
        "condition_id": _safe(a.get("conditionId")),
        "outcome":      _safe(a.get("outcome") or a.get("side")),
        "price_cents":  _norm_price(a.get("price")),
        "size":         _safe(a.get("size") or a.get("shares")),
        "usd_value":    _safe(a.get("usdcSize") or a.get("value")),
    }


# ==============================================================================
# CSV / JSON output
# ==============================================================================

def _save_csv(rows: List[dict], path: str) -> None:
    if not rows:
        print(f"    (no data to write -> {path})")
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"    Saved {len(rows):,} rows -> {path}")


def _save_json_file(data, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"    Saved JSON -> {path}")


# ==============================================================================
# Analytics
# ==============================================================================

def _summarise(wallet: str, trades: List[dict], positions: List[dict],
               closed: List[dict], value_data) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append(f"  SUMMARY  {wallet[:24]}...")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append("=" * 60)

    if value_data:
        val = value_data.get("value") or value_data.get("totalValue") or "n/a"
        try:
            lines.append(f"\n  Portfolio value:  ${float(val):,.2f}")
        except (TypeError, ValueError):
            lines.append(f"\n  Portfolio value:  {val}")

    lines.append(f"\n  Total trades fetched:   {len(trades):,}")
    lines.append(f"  Open positions:         {len(positions):,}")
    lines.append(f"  Closed positions:       {len(closed):,}")

    pnl_vals = []
    for p in closed:
        try:
            pnl_vals.append(float(p.get("pnl", 0) or 0))
        except (TypeError, ValueError):
            pass

    if pnl_vals:
        total_pnl = sum(pnl_vals)
        wins   = [v for v in pnl_vals if v > 0]
        losses = [v for v in pnl_vals if v < 0]
        win_rate = len(wins) / len(pnl_vals) * 100 if pnl_vals else 0
        lines.append(f"\n  Closed position P&L")
        lines.append(f"  {'='*38}")
        lines.append(f"  Total realised P&L:   ${total_pnl:,.2f}")
        lines.append(f"  Win rate:             {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)")
        if wins:
            lines.append(f"  Avg win:              ${sum(wins)/len(wins):,.2f}")
        if losses:
            lines.append(f"  Avg loss:             ${sum(losses)/len(losses):,.2f}")
        if wins and losses:
            avg_win  = sum(wins) / len(wins)
            avg_loss = abs(sum(losses) / len(losses))
            if avg_loss > 0:
                lines.append(f"  Profit factor:        {avg_win/avg_loss:.2f}x")

    mkt_counts = Counter(t.get("market", "") for t in trades if t.get("market"))
    if mkt_counts:
        lines.append(f"\n  Top 10 most-traded markets")
        lines.append(f"  {'='*38}")
        for mkt, cnt in mkt_counts.most_common(10):
            lines.append(f"  {cnt:>5}x  {mkt[:54]}")

    sizes = []
    for t in trades:
        try:
            n = float(t.get("notional_usd") or 0)
            if n > 0:
                sizes.append(n)
        except (TypeError, ValueError):
            pass
    if sizes:
        sizes_sorted = sorted(sizes)
        lines.append(f"\n  Trade size distribution")
        lines.append(f"  {'='*38}")
        lines.append(f"  Median:       ${sizes_sorted[len(sizes_sorted)//2]:,.2f}")
        lines.append(f"  Average:      ${sum(sizes)/len(sizes):,.2f}")
        lines.append(f"  Largest:      ${max(sizes):,.2f}")
        lines.append(f"  Total volume: ${sum(sizes):,.2f}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


# ==============================================================================
# Leaderboard  (official Polymarket API)
# ==============================================================================

def fetch_leaderboard(
    limit: int = 50,
    period: str = "WEEK",
    category: str = "OVERALL",
    order_by: str = "PNL",
) -> List[dict]:
    """
    Pull top traders from the official Polymarket leaderboard API.
    Docs: docs.polymarket.com/api-reference/core/get-trader-leaderboard-rankings

    Parameters
    ----------
    limit    : total records to fetch (the API paginates in batches of 50,
               max offset is 1000 so effective ceiling is ~1050)
    period   : DAY | WEEK | MONTH | ALL
    category : OVERALL | POLITICS | SPORTS | CRYPTO | CULTURE |
               ECONOMICS | TECH | FINANCE | WEATHER | MENTIONS
    order_by : PNL | VOL
    """
    period   = period.upper()
    category = category.upper()
    order_by = order_by.upper()

    print(f"\n  LEADERBOARD  category={category}  period={period}  order={order_by}  n={limit}")
    print(f"  Source: {LEADERBOARD_URL}\n")

    all_rows: List[dict] = []
    offset   = 0
    page_sz  = min(50, limit)   # API hard max is 50 per request

    while len(all_rows) < limit:
        params = {
            "category":   category,
            "timePeriod": period,
            "orderBy":    order_by,
            "limit":      page_sz,
            "offset":     offset,
        }
        data = _get(LEADERBOARD_URL, params=params)
        time.sleep(DELAY)

        if not data or not isinstance(data, list):
            break

        all_rows.extend(data)
        print(f"    Fetched {len(all_rows):,} traders...", end="\r")

        if len(data) < page_sz:
            break
        offset += page_sz

    print()

    if not all_rows:
        print("  [!] Leaderboard returned no data.")
        print("      Check docs.polymarket.com for any API changes.")
        return []

    wallets = []
    for r in all_rows[:limit]:
        wallets.append({
            "rank":       _safe(r.get("rank")),
            "username":   _safe(r.get("userName")),
            "address":    _safe(r.get("proxyWallet")),
            "pnl_usd":    _safe(r.get("pnl")),
            "volume_usd": _safe(r.get("vol")),
            "x_username": _safe(r.get("xUsername")),
            "verified":   str(r.get("verifiedBadge", False)),
            "period":     period,
            "category":   category,
        })

    csv_path = f"{OUT_DIR}/leaderboard_{category.lower()}_{period.lower()}.csv"
    _save_csv(wallets, csv_path)

    # Print table
    print(f"\n  {'#':<5} {'P&L':>12} {'Volume':>12} {'Username':<22}  Address")
    print("  " + "=" * 68)
    for w in wallets[:50]:
        try:
            pnl_str = f"${float(w['pnl_usd']):>10,.0f}"
            vol_str = f"${float(w['volume_usd']):>10,.0f}"
        except (TypeError, ValueError):
            pnl_str = f"{'?':>12}"
            vol_str = f"{'?':>12}"
        verified = " [V]" if w["verified"] == "True" else ""
        name     = (w["username"] or (w["address"][:12] + "..."))[:20]
        addr     = (w["address"][:20] + "...") if len(w["address"]) > 20 else w["address"]
        print(f"  {w['rank']:<5} {pnl_str}  {vol_str}  {name+verified:<22}  {addr}")

    if len(wallets) > 50:
        print(f"\n  ... and {len(wallets)-50} more  see {csv_path}")

    print(f"\n  Full list saved to {csv_path}")
    print("  To analyze a wallet from this list:")
    print("    python3 wallet_analyzer.py --wallet <address>")

    return wallets


# ==============================================================================
# Wallet analysis
# ==============================================================================

def analyze_wallet(wallet: str, since_ts: Optional[int] = None,
                   save_json: bool = False) -> None:
    """Fetch and save complete history for one wallet."""
    addr_short = wallet[:10]
    print(f"\n{'='*60}")
    print(f"  WALLET  {wallet}")
    print(f"{'='*60}")

    os.makedirs(OUT_DIR, exist_ok=True)

    print("\n  [1/5] Portfolio value...")
    value_data = _get(f"{DATA}/value", {"user": wallet})
    time.sleep(DELAY)
    if value_data:
        val = value_data.get("value") or value_data.get("totalValue") or "n/a"
        try:
            print(f"        ${float(val):,.2f}")
        except (TypeError, ValueError):
            print(f"        {val}")

    print(f"\n  [2/5] Fetching full trade history (paginated, {PAGE}/page)...")
    raw_trades = _paginate("/trades", wallet, since_ts=since_ts)
    trades = [_norm_trade(t) for t in raw_trades]
    print(f"        {len(trades):,} trades total")
    _save_csv(trades, f"{OUT_DIR}/{addr_short}_trades.csv")
    if save_json:
        _save_json_file(raw_trades, f"{OUT_DIR}/{addr_short}_trades.json")

    print(f"\n  [3/5] Fetching activity log (paginated)...")
    raw_activity = _paginate("/activity", wallet, since_ts=since_ts)
    activity = [_norm_activity(a) for a in raw_activity]
    print(f"        {len(activity):,} events total")
    _save_csv(activity, f"{OUT_DIR}/{addr_short}_activity.csv")
    if save_json:
        _save_json_file(raw_activity, f"{OUT_DIR}/{addr_short}_activity.json")

    print(f"\n  [4/5] Open positions...")
    raw_pos = _paginate("/positions", wallet)
    positions = [_norm_position(p, "open") for p in raw_pos]
    print(f"        {len(positions):,} open positions")
    _save_csv(positions, f"{OUT_DIR}/{addr_short}_positions.csv")

    print(f"\n  [5/5] Closed positions...")
    raw_closed = _paginate("/closed-positions", wallet)
    closed = [_norm_position(p, "closed") for p in raw_closed]
    print(f"        {len(closed):,} closed positions")
    _save_csv(closed, f"{OUT_DIR}/{addr_short}_closed.csv")

    summary = _summarise(wallet, trades, positions, closed, value_data)
    print("\n" + summary)
    summary_path = f"{OUT_DIR}/{addr_short}_summary.txt"
    with open(summary_path, "w") as f:
        f.write(summary + "\n")
    print(f"\n  Summary saved -> {summary_path}")


# ==============================================================================
# Market holders
# ==============================================================================

def fetch_market_holders(condition_id: str) -> None:
    print(f"\n  MARKET HOLDERS  {condition_id[:32]}...\n")

    rows = []
    offset = 0
    while True:
        data = _get(f"{DATA}/holders",
                    {"conditionId": condition_id, "limit": PAGE, "offset": offset})
        time.sleep(DELAY)
        if not data:
            break
        chunk = data if isinstance(data, list) else data.get("holders", data.get("data", []))
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        offset += PAGE

    if not rows:
        print("  (no holder data)")
        return

    normalised = []
    for h in rows:
        normalised.append({
            "address": h.get("proxyWallet") or h.get("address") or h.get("user") or "",
            "outcome": h.get("outcome") or h.get("side") or "",
            "size":    h.get("size") or h.get("shares") or "",
            "value":   h.get("value") or h.get("currentValue") or "",
        })

    slug = condition_id[:12]
    _save_csv(normalised, f"{OUT_DIR}/holders_{slug}.csv")

    print(f"  {len(normalised)} holders\n")
    print(f"  {'Address':<24} {'Outcome':<8} {'Size':>12} {'Value':>12}")
    print("  " + "-" * 60)
    for h in normalised[:20]:
        try:
            val_str = f"${float(h['value']):>10,.2f}"
        except (TypeError, ValueError):
            val_str = f"{h['value']:>12}"
        print(f"  {h['address'][:22]:<24} {h['outcome']:<8} {str(h['size']):>12} {val_str}")
    if len(normalised) > 20:
        print(f"  ... and {len(normalised)-20} more  see {OUT_DIR}/holders_{slug}.csv")


# ==============================================================================
# CLI
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Polymarket wallet analyzer - full history, paginated, CSV export.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Browse the leaderboard to discover wallets
  python3 wallet_analyzer.py --leaderboard
  python3 wallet_analyzer.py --leaderboard --period MONTH --category POLITICS

  # Analyze a specific wallet
  python3 wallet_analyzer.py --wallet 0xABC123...

  # Pull leaderboard and analyze the top 5 immediately
  python3 wallet_analyzer.py --leaderboard --analyze-top 5

  # Multiple wallets
  python3 wallet_analyzer.py --wallet 0xABC 0xDEF

  # Only recent trades
  python3 wallet_analyzer.py --wallet 0xABC --since 2025-01-01

  # Top holders for a market
  python3 wallet_analyzer.py --market 0xCONDITION_ID
        """,
    )
    parser.add_argument(
        "--wallet", nargs="+", metavar="ADDR",
        help="One or more proxy wallet addresses to analyze",
    )
    parser.add_argument(
        "--wallet-file", metavar="FILE",
        help="Text file with one wallet address per line",
    )
    parser.add_argument(
        "--since", metavar="YYYY-MM-DD",
        help="Only fetch records on or after this date (UTC)",
    )
    parser.add_argument(
        "--leaderboard", action="store_true",
        help="Pull the Polymarket leaderboard (use with --period/--category/--order-by/--limit)",
    )
    parser.add_argument(
        "--period", default="WEEK",
        choices=["DAY", "WEEK", "MONTH", "ALL"],
        help="Leaderboard time period (default: WEEK)",
    )
    parser.add_argument(
        "--category", default="OVERALL",
        choices=sorted(VALID_CATEGORIES),
        help="Leaderboard category (default: OVERALL)",
    )
    parser.add_argument(
        "--order-by", default="PNL",
        choices=["PNL", "VOL"],
        dest="order_by",
        help="Leaderboard sort order (default: PNL)",
    )
    parser.add_argument(
        "--limit", type=int, default=50,
        help="Number of leaderboard entries to fetch (default: 50, max ~1000)",
    )
    parser.add_argument(
        "--analyze-top", type=int, default=0, metavar="N",
        dest="analyze_top",
        help="After fetching leaderboard, run full wallet analysis on the top N",
    )
    parser.add_argument(
        "--market", metavar="CONDITION_ID",
        help="Show top holders for a specific market (0x condition ID)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Also save raw JSON alongside CSV files",
    )
    parser.add_argument(
        "--out", metavar="DIR", default=OUT_DIR,
        help=f"Output directory (default: {OUT_DIR})",
    )
    args = parser.parse_args()

    global OUT_DIR
    OUT_DIR = args.out
    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  POLYMARKET WALLET ANALYZER")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"{'='*60}")

    # Parse --since
    since_ts = None
    if args.since:
        try:
            dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            since_ts = int(dt.timestamp())
            print(f"\n  Filtering: records on/after {args.since}")
        except ValueError:
            print(f"  [!] Invalid --since date '{args.since}'. Use YYYY-MM-DD.")
            sys.exit(1)

    # Collect wallet addresses
    wallets = list(args.wallet or [])
    if args.wallet_file:
        try:
            with open(args.wallet_file) as f:
                file_wallets = [
                    line.strip() for line in f
                    if line.strip() and not line.startswith("#")
                ]
            wallets.extend(file_wallets)
            print(f"  Loaded {len(file_wallets)} wallets from {args.wallet_file}")
        except FileNotFoundError:
            print(f"  [!] File not found: {args.wallet_file}")
            sys.exit(1)

    # Leaderboard
    lb_wallets = []
    if args.leaderboard:
        lb_wallets = fetch_leaderboard(
            limit=args.limit,
            period=args.period,
            category=args.category,
            order_by=args.order_by,
        )
        # Optionally analyze top N from the leaderboard
        if args.analyze_top > 0 and lb_wallets:
            top_addrs = [
                w["address"] for w in lb_wallets[:args.analyze_top]
                if w.get("address")
            ]
            print(f"\n  Analyzing top {len(top_addrs)} wallets from leaderboard...")
            wallets = top_addrs + wallets   # prepend so they go first

    # Market holders
    if args.market:
        fetch_market_holders(args.market)

    # Nothing to do
    if not wallets and not args.leaderboard and not args.market:
        parser.print_help()
        print("\n  [!] Specify --wallet, --leaderboard, or --market.")
        sys.exit(0)

    # Wallet analysis
    for i, wallet in enumerate(wallets, 1):
        if len(wallets) > 1:
            print(f"\n  [{i}/{len(wallets)}]  {wallet}")
        analyze_wallet(wallet, since_ts=since_ts, save_json=args.json)

    print(f"\n\n{'='*60}")
    print(f"  ALL DONE  output files in ./{OUT_DIR}/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
