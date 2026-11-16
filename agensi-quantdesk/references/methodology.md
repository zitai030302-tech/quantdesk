# Execution, risk and statistics

- Signals consume the prefix of completed bars. Earliest execution is the
  next open. Explicit exits at the open take precedence over intrabar extremes.
  Resting protection crossed at the open fills from that open before slippage.
  If both stop and target are touched inside a bar, the stop wins. An intrabar
  fill's timestamp is the bar close label. The exact time is unavailable.
- Market buys and all modeled sells apply adverse slippage. An entry outside
  its signal-time ATR bracket or beyond cash at the execution price is skipped.
  Positions are long-only, unlevered, single-symbol, one at a time. The fixed
  size is calculated from signal-close ATR risk and checked for cash at fill.
  Gaps and fees can make losses exceed nominal sizing risk.
- The simulated rule uses a 0.000001 quantity step, a 1 quote-unit minimum
  notional at sizing/validation and a 0.01 tick field. It does not query live
  symbol metadata or snap simulated fill prices to the tick. No depth, funding,
  liquidity or market impact beyond fixed slippage is modeled.
- Daily realized-loss accounting rolls on UTC fill and bar dates. The consecutive-loss
  rule may pause the strategy through the end of a replay. End positions are
  marked at last close and retain charged entry fees. Open trades are excluded
  from the closed trade count and win rate. No forced liquidation is assumed.
- Total return is ending marked equity divided by starting cash minus one.
  Maximum drawdown is the largest peak-to-trough loss as a fraction of peak,
  including starting cash in the curve. Win rate divides positive net-PnL
  round trips by closed trades. Turnover divides gross filled entry and exit
  notionals by mean marked equity, including starting cash.
- Returns are simple bar-to-bar equity changes. Sharpe divides arithmetic mean
  by population standard deviation. Sortino divides the same mean by the
  root mean square of negative returns across all observations. Both use zero
  risk-free/target rates and square-root scaling using fixed 365-day crypto
  periods. Annualized return compounds the gross result to 365 days for windows
  of 30 days or more. Sharpe ratios over short samples are descriptive and can
  be unstable. Undefined denominators yield unavailable metrics.
- Fees use executed notional. Slippage cost measures adverse price changes
  versus modeled reference fill prices. The sum reports implementation cost.
  Net equity already reflects both effects.
- A like-for-like comparison verifies a common sample. Parameter selection
  from the same sample can overfit. Use a separate chronological holdout to
  assess a chosen configuration. Single-symbol tests make no claims about
  a historical universe, survivorship or delisted assets.
- Paper checks simulated cash including costs, post-buy exposure and sell
  inventory. The provided limit is an entry limit tested at the hypothetical
  execution price. Later mark changes can move exposure through it. The SQLite
  ledger includes the actual simulation events and final position. The
  deterministic reports exclude internally generated SQLite record IDs and
  timestamps. Portfolio risk, automatic liquidation and continuation from a
  previous SQLite account are outside the paper scenario model.
