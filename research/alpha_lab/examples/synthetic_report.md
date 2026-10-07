# Local factor experiment

Generated/local data; these results are not WorldQuant platform metrics.

| Factor | Train rank IC | Holdout rank IC | Holdout Sharpe (252) | Holdout drawdown |
|---|---:|---:|---:|---:|
| reversal_5 | 0.000 | 0.018 | -0.464 | 3.94% |
| momentum_20 | -0.018 | -0.030 | -2.624 | 8.31% |
| volume_surprise | -0.005 | -0.004 | -4.130 | 10.53% |
| low_volatility | -0.002 | -0.024 | -2.391 | 6.57% |

The split and candidate list are fixed before evaluation. Development correlation does not inspect holdout dates. No candidate is automatically selected using holdout performance.

Signals are observed at close t, executed at close t+1, and earn close t+1 to t+2 returns. Transaction cost is charged on changes from drifted holdings. Short financing, market impact, and borrow availability are not modeled.
