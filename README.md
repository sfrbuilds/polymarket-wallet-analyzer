# Polymarket Wallet Analyzer

Pull complete trade history, positions, and P&L analytics for any Polymarket wallet. Paginated, CSV export, leaderboard discovery. No API key required.

---

## Quick start

```bash
pip install requests
python3 wallet_analyzer.py --help
```

---

## Typical workflow

**One command to see everything**

```bash
python3 wallet_analyzer.py --leaderboard
```

This pulls the top 50 traders for the week, prints the ranked table, then automatically runs a full analysis on the #1 wallet — trade history, positions, P&L summary, CSVs. No extra steps.

**Find and analyze the best wallet in a specific category**

Each category has its own leaderboard. These one-liners pull the top trader in that category and analyze their full history:

```bash
# Best political trader this month
python3 wallet_analyzer.py --leaderboard --category POLITICS --period MONTH

# Best crypto trader all time
python3 wallet_analyzer.py --leaderboard --category CRYPTO --period ALL

# Best sports trader this week
python3 wallet_analyzer.py --leaderboard --category SPORTS --period WEEK

# Best economics/macro trader this month
python3 wallet_analyzer.py --leaderboard --category ECONOMICS --period MONTH

# Best tech trader all time, top 3 analyzed
python3 wallet_analyzer.py --leaderboard --category TECH --period ALL --analyze-top 3
```

Available categories: `OVERALL`, `POLITICS`, `SPORTS`, `CRYPTO`, `CULTURE`, `ECONOMICS`, `TECH`, `FINANCE`, `WEATHER`, `MENTIONS`

Available periods: `DAY`, `WEEK`, `MONTH`, `ALL`

**Find and analyze the best wallet in a specific category**

Each category has its own leaderboard. These one-liners pull the top trader in that category and analyze their full history:

```bash
# Best political trader this month
python3 wallet_analyzer.py --leaderboard --category POLITICS --period MONTH

# Best crypto trader all time
python3 wallet_analyzer.py --leaderboard --category CRYPTO --period ALL

# Best sports trader this week
python3 wallet_analyzer.py --leaderboard --category SPORTS --period WEEK

# Best economics/macro trader this month
python3 wallet_analyzer.py --leaderboard --category ECONOMICS --period MONTH

# Best tech trader all time, top 3 analyzed
python3 wallet_analyzer.py --leaderboard --category TECH --period ALL --analyze-top 3
```

Available categories: `OVERALL`, `POLITICS`, `SPORTS`, `CRYPTO`, `CULTURE`, `ECONOMICS`, `TECH`, `FINANCE`, `WEATHER`, `MENTIONS`

Available periods: `DAY`, `WEEK`, `MONTH`, `ALL`

**Browse first, then pick who to analyze**

```bash
# Show the leaderboard without analyzing anyone
python3 wallet_analyzer.py --leaderboard --category POLITICS --analyze-top 0

# Then analyze a specific wallet you found interesting
python3 wallet_analyzer.py --wallet 0xABC123...
```

**Compare top wallets across categories**

```bash
# Run back to back — each saves its own CSV
python3 wallet_analyzer.py --leaderboard --category POLITICS --period MONTH --analyze-top 0
python3 wallet_analyzer.py --leaderboard --category CRYPTO --period MONTH --analyze-top 0
python3 wallet_analyzer.py --leaderboard --category ECONOMICS --period MONTH --analyze-top 0
# CSVs land in output/leaderboard_politics_month.csv etc.
```

---

## All options

```bash
# Multiple wallets in one run
python3 wallet_analyzer.py --wallet 0xABC 0xDEF 0xGHI

# Load wallets from a file (one address per line, # for comments)
python3 wallet_analyzer.py --wallet-file my_wallets.txt

# Only pull records since a specific date
python3 wallet_analyzer.py --wallet 0xABC --since 2025-01-01

# Save raw JSON alongside CSV
python3 wallet_analyzer.py --wallet 0xABC --json

# Top holders for a specific market
python3 wallet_analyzer.py --market 0xCONDITION_ID

# Change output directory
python3 wallet_analyzer.py --wallet 0xABC --out my_analysis/
```

---

## Leaderboard options

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--period` | DAY, WEEK, MONTH, ALL | WEEK | Time window |
| `--category` | OVERALL, POLITICS, SPORTS, CRYPTO, CULTURE, ECONOMICS, TECH, FINANCE, WEATHER, MENTIONS | OVERALL | Market category |
| `--order-by` | PNL, VOL | PNL | Sort order |
| `--limit` | 1-1000 | 50 | Number of traders to fetch |
| `--analyze-top` | N | off | Also run full analysis on the top N wallets |

---

## Output files

All files written to `./output/` (or `--out DIR`):

| File | Contents |
|------|----------|
| `{wallet}_trades.csv` | All filled trades, full history, paginated |
| `{wallet}_activity.csv` | All on-chain events (buys, sells, claims, etc.) |
| `{wallet}_positions.csv` | Current open positions |
| `{wallet}_closed.csv` | Closed/resolved positions with P&L |
| `{wallet}_summary.txt` | P&L summary, win rate, top markets, size stats |
| `leaderboard_{cat}_{period}.csv` | Leaderboard results |
| `holders_{id}.csv` | Top holders for a market (`--market` only) |

---

## What gets fetched per wallet

1. **Portfolio value** - current USDC balance
2. **Full trade history** - paginated in batches of 500 until exhausted. Columns: timestamp, market, outcome, price (cents), size, notional USD, tx hash
3. **Activity log** - all on-chain events including non-trade activity
4. **Open positions** - current holdings with avg price and current value
5. **Closed positions** - resolved markets with realised P&L

The summary file includes:

- Total realised P&L
- Win rate (% of closed positions profitable)
- Average win / average loss
- Profit factor
- Top 10 most-traded markets by count
- Trade size distribution (median, average, largest, total volume)

---

## How to find a wallet address

**Option 1: Use the leaderboard (easiest)**

```bash
python3 wallet_analyzer.py --leaderboard --analyze-top 0
```

The address column is printed for every trader. Copy any one you want.

**Option 2: From a Polymarket profile page**

Go to any trader's profile on polymarket.com. The URL contains their wallet address:

```
polymarket.com/profile/0xf8831548531d56ad6a...
                        ^^^^^^^^^^^^^^^^^^^^
                        this is the proxy wallet address
```

Copy the full `0x...` string and pass it to `--wallet`.

**Option 3: From a market's leaderboard**

On any market page, click "Leaderboard" to see top holders. Their addresses appear in the table or in the URL when you click their profile.

**Option 4: From the top holders endpoint**

```bash
python3 wallet_analyzer.py --market 0xCONDITION_ID
```

This shows the largest position holders for any specific market.

Note: Polymarket uses proxy wallets, not EOA (MetaMask) wallets. Always use the address from the Polymarket profile URL, not your MetaMask address.

---

## How to find a condition ID (for `--market`)

```bash
curl -s "https://gamma-api.polymarket.com/events?slug=YOUR-MARKET-SLUG" \
  | python3 -m json.tool | grep conditionId
```

Or from the market page in your browser DevTools: Network tab, filter for `clob.polymarket.com`.

---

## Pagination

The script fetches records in batches of 500 and continues until the API returns a short page. For large wallets with thousands of trades this takes a minute or two. Progress is shown per page.

Use `--since YYYY-MM-DD` to limit to recent data and speed things up.

---

## Notes

- Rate limited to ~3 req/sec by default (adjustable via `DELAY` constant)
- Prices are normalised to cents (0.67 becomes 67.00)
- Timestamps are normalised to UTC ISO-8601 strings
- The leaderboard uses the official Polymarket data API (docs.polymarket.com/api-reference/core/get-trader-leaderboard-rankings)

---

## License

MIT. No API key, no rate limits beyond being polite.
