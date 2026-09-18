---
name: mean-reversion-testing
description: This skill should be used when the user asks to "test for mean reversion", "run an ADF test", "check if a series is stationary", "compute the Hurst exponent", "estimate half-life of mean reversion", "is this spread mean-reverting", "unit root test", "pairs trading stationarity check", "cointegration residual test", "check random walk vs mean reversion", or needs to statistically validate whether a time series (price spread, ratio, regression residual, macro series) reverts to a long-run mean. Covers the three practitioner tests — Augmented Dickey–Fuller (ADF), Hurst exponent, and half-life — plus interpretation, pitfalls, and ready-to-run Python code.
version: 1.0.0
---

# Mean Reversion Testing Skill

Statistically test whether a time series is mean-reverting before treating it as one. The full reference article is saved alongside this skill in `mean-reversion-testing.md` — read it for derivations, references, and extended discussion.

## When to Use

Trigger this skill when:

- Deciding whether a spread, ratio, or regression residual is tradeable (pairs/stat-arb screening)
- Calibrating mean-reverting stochastic models (Ornstein–Uhlenbeck, Vasicek)
- Checking whether a claimed alpha factor is a genuine mean-reverting residual or an in-sample artefact
- Testing macro series (real exchange rates, yield spreads, real commodity prices) for reversion
- Validating stationarity assumptions underlying a strategy

## Core Distinction

- **Random walk:** $y_t = \mu + y_{t-1} + \varepsilon_t$ — shocks are permanent, variance grows with time.
- **Mean-reverting (AR(1)):** $y_t = \alpha + \rho\, y_{t-1} + \varepsilon_t$ with $|\rho| < 1$ — pulled toward long-run mean $\alpha/(1-\rho)$ at speed $1-\rho$.

Testing for mean reversion = testing whether $\rho$ is statistically $< 1$.

## The Three Tests (run all three)

### 1. Augmented Dickey–Fuller (ADF)

Null = unit root (random walk); alternative = stationary (mean-reverting).

$$\Delta y_t = \alpha + \beta t + \gamma\, y_{t-1} + \sum_{i=1}^{p}\delta_i\,\Delta y_{t-i} + \varepsilon_t$$

- **Reject** unit root if statistic is more negative than the critical value (p-value < 0.05) → consistent with mean reversion.
- **Fail to reject** → do NOT conclude random walk; you only failed to find evidence against it.
- Specification: constant-no-trend is the default for spreads and financial residuals. Choose based on what the series *should* look like under the alternative, not what makes the test pass.
- Lag length: let software pick via AIC/BIC, or use Schwert's rule $p_{\max} = \lfloor 12(T/100)^{1/4}\rfloor$ as an upper bound. Never tune lags to minimise p-value (data snooping).

```python
import numpy as np, pandas as pd
from statsmodels.tsa.stattools import adfuller

def adf_report(series, name="series", regression="c"):
    stat, p, n_lags, n_obs, crit, _ = adfuller(series.dropna(), autolag="AIC", regression=regression)
    verdict = "Reject unit root (mean-reverting)" if p < 0.05 else "Cannot reject unit root"
    print(f"{name}: stat={stat:.4f} p={p:.4f} lags={n_lags} obs={n_obs} -> {verdict}")
```

### 2. Hurst Exponent (corroborating, non-parametric)

Estimate via variance-of-lagged-differences scaling: $\mathrm{Var}(y_{t+\tau}-y_t) \propto \tau^{2H}$.

- $H = 0.5$ → random walk
- $H < 0.5$ → anti-persistent (mean-reverting)
- $H > 0.5$ → persistent (trending)

```python
import numpy as np, pandas as pd

def hurst_exponent(series, max_lag=100):
    s = series.dropna().values
    lags = range(2, max_lag)
    tau = [np.sqrt(np.var(s[lag:] - s[:-lag])) for lag in lags]
    slope, _ = np.polyfit(np.log(lags), np.log(tau), 1)
    return slope  # slope == H (variance-of-differences estimator)
```

Noisy below a few thousand observations; use only to *triangulate* with ADF, never standalone.

### 3. Half-Life of Mean Reversion

Even a mean-reverting series is useless unless reversion happens on a tradeable timescale.

From $\Delta y_t = \alpha + \lambda\, y_{t-1} + \varepsilon_t$ with $\lambda = \rho - 1 < 0$:

$$t_{1/2} = -\ln 2 \,/\, \lambda$$

```python
import numpy as np, pandas as pd, statsmodels.api as sm

def half_life(series):
    s = series.dropna()
    lag = s.shift(1).dropna()
    delta = s.diff().dropna()
    a = pd.concat([delta, lag], axis=1, join="inner"); a.columns = ["delta","lag"]
    X = sm.add_constant(a["lag"])
    lam = sm.OLS(a["delta"], X).fit().params["lag"]
    return np.inf if lam >= 0 else -np.log(2) / lam
```

Relates to OU reversion speed $\theta$ by $t_{1/2} = \ln 2 / \theta$.

## Verdict Rule

A defensible mean-reversion claim needs **all three consistent**:

1. ADF rejects the unit root at conventional significance.
2. Hurst is materially below 0.5.
3. Half-life is finite and short relative to the intended holding horizon.

Disagreement = investigate: structural breaks, fat tails biasing Hurst, serial correlation violating ADF lag assumptions.

## Pitfalls to Flag

- **In-sample cherry-picking:** scanning hundreds of pairs and picking the ones that reject inflates false positives. Apply Bonferroni/FDR, or reserve tests for series with prior theoretical reason to revert.
- **Cointegration residuals:** use Phillips–Ouliaris critical values, not standard ADF — the regression itself adds sampling variation.
- **Structural breaks:** test sub-samples separately, or use Zivot–Andrews / Bai–Perron.
- **Small samples:** ADF low power < ~500 obs; Hurst noisy < ~1000 obs; half-life CIs wide.
- **Volatility clustering (GARCH):** ADF asymptotically valid but small-sample distortion — use a wild-bootstrap ADF if residuals show strong ARCH effects.
- **Intraday:** microstructure noise (bid–ask bounce) creates spurious anti-persistence; intraday seasonality violates innovation stationarity. Filter both first.

## Tradeability Check

A low ADF p-value is necessary, not sufficient. A real strategy additionally needs:

- Half-life short relative to holding horizon
- Transaction costs small relative to typical reversion amplitude
- Stability out of sample

A p-value of 0.001 on a 200-day half-life series is a statistical curiosity, not a strategy.

## Source

Full article (derivations, ADF vs KPSS, intraday notes, references): `mean-reversion-testing.md` in this skill directory. Original: <https://www.quantt.co.uk/resources/mean-reversion-testing> (via Quantocracy).
