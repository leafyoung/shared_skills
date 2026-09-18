# Testing for Mean Reversion: ADF, Hurst Exponent and Half-Life

> Source: <https://www.quantt.co.uk/resources/mean-reversion-testing?ref=quantocracy> (via Quantocracy)
> Saved as reference material for the `mean-reversion-testing` skill.

---

## What Does It Mean for a Series to Be Mean-Reverting?

A time series is **mean-reverting** if it tends to return to a stable long-run level after being displaced from it. In pure form, that means the process has a well-defined unconditional mean and a variance that does not grow without bound; shocks decay rather than accumulate.

This is the opposite of a **random walk**, where each innovation is permanently absorbed into the level and variance grows linearly with time. Most raw asset prices behave far more like random walks than like mean-reverting processes. Spreads, ratios, residuals from a regression, and certain macroeconomic variables are more plausible mean-reversion candidates.

Testing for mean reversion is one of the most common statistical tasks in quantitative finance. It underpins pairs trading, statistical arbitrage, curve-fitting checks on residuals, and the calibration of stochastic models such as the [Ornstein–Uhlenbeck process](https://www.quantt.co.uk/resources/ornstein-uhlenbeck-process) and the [Vasicek model](https://www.quantt.co.uk/resources/vasicek-model-explained). Getting the test right — and understanding its assumptions — matters more than the strategy that sits on top. The formal framework follows Hamilton (1994) and Enders (2014); the finance-specific treatment of unit-root testing on returns and spreads is covered in Tsay (2010) and Brooks (2019).

This article walks through the three tests that a practitioner should always run before treating a series as mean-reverting: the Augmented Dickey–Fuller (ADF) test, the Hurst exponent, and the half-life of mean reversion.

---

## Random Walk vs Mean Reversion: The Formal Distinction

Let $y_t$ be a time series observed at equally spaced times $t = 1, 2, \dots, T$.

A **pure random walk** with drift $\mu$ is:

$$y_t = \mu + y_{t-1} + \varepsilon_t$$

where $\varepsilon_t$ is a zero-mean innovation. The best forecast of $y_{t+h}$ is simply $y_t + h\mu$; shocks never fade.

A **mean-reverting process** in its simplest linear form is:

$$y_t = \alpha + \rho \, y_{t-1} + \varepsilon_t, \quad |\rho| < 1$$

Here $y_t$ is pulled back toward its long-run mean $\alpha / (1 - \rho)$ at a speed governed by $(1 - \rho)$. The closer $\rho$ is to 1, the slower the reversion; the closer to 0, the faster.

The knife edge $\rho = 1$ is the random walk. Testing for mean reversion is therefore a test of whether $\rho$ is statistically different from 1 (equivalently, whether the coefficient on $y_{t-1}$ in the differenced regression is different from 0).

---

## Test 1: The Augmented Dickey–Fuller Test

The Augmented Dickey–Fuller (ADF) test is the workhorse unit-root test in econometrics. Introduced by Dickey and Fuller (1979) and extended to allow lagged difference terms by Said and Dickey (1984), it tests the null hypothesis that a series has a unit root (is a random walk) against the alternative that it is stationary (mean-reverting).

### The Regression

The ADF test estimates:

$$\Delta y_t = \alpha + \beta\, t + \gamma\, y_{t-1} + \sum_{i=1}^{p}\delta_i\, \Delta y_{t-i} + \varepsilon_t$$

where $\Delta y_t = y_t - y_{t-1}$. The null hypothesis is $\gamma = 0$ (unit root); the alternative is $\gamma < 0$ (mean reversion). The lag terms $\Delta y_{t-i}$ soak up short-run autocorrelation so that the residuals are approximately white noise.

The test statistic is the t-statistic on $\hat{\gamma}$, but it does **not** follow a standard t distribution under the null — it has the Dickey–Fuller distribution, which is tabulated. Software reports critical values at the 1%, 5%, and 10% levels, and typically returns a p-value.

### How to Interpret the Result

- If the ADF statistic is **more negative** than the critical value (equivalently, p-value < your chosen significance level), reject the unit-root null. The series is consistent with mean reversion.
- If not, you cannot reject the unit-root null. Do **not** conclude that the series is a random walk — you have only failed to find evidence against it.

### Choosing the Regression Specification

Three specifications are common:

1. **No constant, no trend** — appropriate only for series with zero mean.
2. **Constant, no trend** — the default for spreads, log-price differences, and most financial residuals.
3. **Constant and trend** — for series that may revert around a deterministic trend.

The specification matters because the critical values differ. Choose based on what the series should look like under the alternative, not on what makes the test pass.

### Choosing the Lag Length

Too few lags leave autocorrelation in the residuals and bias the test. Too many reduce power. The two standard rules are:

- **Schwert's rule:** $p_{\max} = \lfloor 12 \cdot (T/100)^{1/4} \rfloor$.
- **Information criteria:** choose the lag length that minimises AIC or BIC.

Most statistical packages will do this automatically if asked.

### Python: Running the ADF Test

```python
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

def adf_report(series: pd.Series, name: str = "series", regression: str = "c") -> None:
    """Print an ADF test report for a time series."""
    series = series.dropna()
    stat, p_value, n_lags, n_obs, crit_values, _ = adfuller(
        series, autolag="AIC", regression=regression
    )
    print(f"=== ADF Test: {name} ===")
    print(f"  ADF statistic:     {stat:.4f}")
    print(f"  p-value:           {p_value:.4f}")
    print(f"  Lags used:         {n_lags}")
    print(f"  Observations used: {n_obs}")
    for level, cv in crit_values.items():
        print(f"  Critical value {level}: {cv:.4f}")
    verdict = "Reject unit root (mean-reverting)" if p_value < 0.05 else "Cannot reject unit root"
    print(f"  -> {verdict}")


# --- Example: compare a random walk and an AR(1) with rho = 0.6 ---
np.random.seed(42)
n = 1000

random_walk = pd.Series(np.cumsum(np.random.normal(0, 1, n)))

ar1 = np.zeros(n)
for t in range(1, n):
    ar1[t] = 0.6 * ar1[t - 1] + np.random.normal(0, 1)
ar1 = pd.Series(ar1)

adf_report(random_walk, "random walk")
adf_report(ar1, "AR(1) with rho=0.6")
```

For the AR(1) series with $\rho = 0.6$, the ADF statistic is typically strongly negative and the p-value is essentially zero. For the random walk, the statistic hovers near zero and the p-value is well above any conventional threshold.

---

## Test 2: The Hurst Exponent

The Hurst exponent ($H$) measures how the range of cumulative deviations of a series scales with the observation window. Introduced by Hurst (1951) in hydrology and popularised in finance by Mandelbrot and Wallis (1969), it provides a complementary, non-parametric view of persistence:

- $H = 0.5$ — the series behaves like a random walk.
- $H < 0.5$ — the series is **anti-persistent** (mean-reverting): up moves tend to be followed by down moves.
- $H > 0.5$ — the series is **persistent** (trending): up moves tend to be followed by more up moves.

### Estimation via Variance Scaling

The classical rescaled-range (R/S) estimator is finicky in small samples. A more robust practitioner's estimator uses the variance of lagged differences:

$$\mathrm{Var}(y_{t+\tau} - y_t) \propto \tau^{2H}$$

Taking logs, $\log \mathrm{Var}(\Delta_\tau y) = 2H \log \tau + c$. Regressing the log variance against $\log \tau$ over a range of lags gives a slope of $2H$, from which $H$ is recovered as $\text{slope} / 2$.

### Python: Estimating the Hurst Exponent

```python
import numpy as np
import pandas as pd

def hurst_exponent(series: pd.Series, max_lag: int = 100) -> float:
    """Estimate the Hurst exponent via variance of lagged differences."""
    series = series.dropna().values
    lags = range(2, max_lag)
    tau = [np.sqrt(np.var(np.subtract(series[lag:], series[:-lag]))) for lag in lags]
    poly = np.polyfit(np.log(lags), np.log(tau), 1)
    return poly[0] * 2.0 / 2.0  # slope is already H, kept explicit for clarity


np.random.seed(7)
random_walk = pd.Series(np.cumsum(np.random.normal(0, 1, 5000)))
trending = pd.Series(np.cumsum(np.random.normal(0.05, 1, 5000)))
mean_reverting = pd.Series(np.sin(np.linspace(0, 60 * np.pi, 5000)) + np.random.normal(0, 0.3, 5000))

print(f"Hurst (random walk):     {hurst_exponent(random_walk):.3f}")
print(f"Hurst (trending):        {hurst_exponent(trending):.3f}")
print(f"Hurst (mean-reverting):  {hurst_exponent(mean_reverting):.3f}")
```

The Hurst exponent is best used as a triangulation tool alongside the ADF test rather than as a standalone verdict. Estimates are noisy for series with fewer than a few thousand observations, and short-horizon Hurst values can differ from long-horizon ones. If ADF rejects the unit root and $H$ is materially below 0.5, the mean-reversion conclusion is well supported.

---

## Test 3: Half-Life of Mean Reversion

Even when a series is statistically mean-reverting, that fact is useless for trading unless the reversion happens on a time scale you can capture. The **half-life** answers this: how long, on average, does it take for the series to close half the distance back to its mean?

### Derivation

Starting from the AR(1) form $y_t = \alpha + \rho\, y_{t-1} + \varepsilon_t$, subtract $y_{t-1}$ from both sides:

$$\Delta y_t = \alpha + (\rho - 1)\, y_{t-1} + \varepsilon_t = \alpha + \lambda\, y_{t-1} + \varepsilon_t$$

where $\lambda = \rho - 1 < 0$ for a mean-reverting series. Estimating this regression by OLS gives an estimate of $\lambda$. The half-life is then:

$$t_{1/2} = -\ln 2 \,/\, \lambda$$

A half-life of 5 days means it takes roughly a week for a shock to decay to half its size. A half-life of 250 days on a daily series is technically mean-reverting but essentially useless in a trading window.

### Python: Estimating Half-Life

```python
import numpy as np
import pandas as pd
import statsmodels.api as sm

def half_life(series: pd.Series) -> float:
    """Estimate the half-life of mean reversion from an AR(1) fit."""
    series = series.dropna()
    lag = series.shift(1).dropna()
    delta = series.diff().dropna()
    aligned = pd.concat([delta, lag], axis=1, join="inner")
    aligned.columns = ["delta", "lag"]
    X = sm.add_constant(aligned["lag"])
    model = sm.OLS(aligned["delta"], X).fit()
    lam = model.params["lag"]
    if lam >= 0:
        return np.inf  # not mean-reverting
    return -np.log(2) / lam


np.random.seed(11)
fast = np.zeros(2000)
slow = np.zeros(2000)
for t in range(1, 2000):
    fast[t] = 0.4 * fast[t - 1] + np.random.normal(0, 1)   # rho = 0.4
    slow[t] = 0.95 * slow[t - 1] + np.random.normal(0, 1)  # rho = 0.95

print(f"Half-life (fast, rho=0.4):  {half_life(pd.Series(fast)):.2f} periods")
print(f"Half-life (slow, rho=0.95): {half_life(pd.Series(slow)):.2f} periods")
```

The theoretical half-lives are $-\ln 2 / \ln 0.4 \approx 0.76$ and $-\ln 2 / \ln 0.95 \approx 13.5$ periods respectively; the fits should be close to these.

---

## Putting the Three Together

A single test is rarely convincing. A defensible mean-reversion claim usually rests on three consistent signals:

1. **ADF rejects the unit root** at conventional significance levels.
2. **Hurst exponent** is materially below 0.5.
3. **Half-life** is finite and short enough for the intended trading horizon.

When these agree, the series behaves like a mean-reverting process on the time scale of interest. When they disagree, treat the result as ambiguous and investigate why. Common causes of disagreement include:

- Structural breaks that make the series appear non-stationary in-sample.
- Fat-tailed innovations that inflate the R/S range and bias the Hurst estimate.
- Serial correlation in innovations that violates ADF assumptions unless enough lags are included.

---

## Practical Pitfalls

### In-Sample Cherry-Picking

The ADF and Hurst tests were designed for pre-specified series. If you scan hundreds of possible pairs or spreads and pick the ones that reject the null, multiple-testing bias inflates false positives. Apply a Bonferroni or FDR correction, or reserve the tests for series you have prior theoretical reason to expect will revert.

### Non-Stationary Cointegration Residuals

For pairs trading, the mean-reversion test is applied to the residual of a regression between two prices. That residual is only meaningful if the two series are cointegrated. The Engle–Granger procedure uses a modified ADF critical value (the Phillips–Ouliaris values) because the regression itself introduces sampling variation. Using the standard ADF critical values here overstates significance.

### Structural Breaks

Regime changes — a decimalisation event, a policy shift, a new market maker — can produce a series that looks mean-reverting within each regime but non-stationary across the break. If a break is suspected, test each sub-sample separately, or use tests that allow for a single break (Zivot–Andrews) or multiple breaks (Bai–Perron).

### Small Samples

With fewer than a few hundred observations, ADF has low power against near-unit-root alternatives and Hurst estimates are noisy. Half-life estimates from short samples have wide confidence intervals. A rule of thumb: at least 500 observations for daily ADF and 1,000+ for Hurst.

### Volatility Clustering

Financial residuals often exhibit GARCH-style volatility clustering. The ADF test remains asymptotically valid under conditional heteroscedasticity, but small-sample rejection rates can be distorted. If your residuals show strong ARCH effects, complement the ADF test with a wild-bootstrap version.

---

## Applications in Quantitative Finance

**Pairs and statistical arbitrage.** The core screen for any mean-reversion strategy is: is the spread stationary, and does it revert on a tradeable time scale? Half-life directly informs holding period and stop-loss design.

**Model calibration.** The Ornstein–Uhlenbeck and Vasicek models assume mean reversion. Their calibration produces an estimate of the reversion speed ($\theta$), which is related to the half-life by $t_{1/2} = \ln(2) / \theta$.

**Risk premium research.** Many purported alpha factors are essentially claims that certain residuals mean-revert. Testing rigorously distinguishes real anomalies from spurious in-sample fits.

**Macro trading.** Real exchange rates, inflation-adjusted commodity prices, and yield spreads are classic examples of macro series with theoretical reasons to mean-revert. Empirical tests provide the evidence.

---

## References

- Brooks, C. (2019). *Introductory Econometrics for Finance* (4th ed.). Cambridge University Press.
- Dickey, D. A., & Fuller, W. A. (1979). Distribution of the estimators for autoregressive time series with a unit root. *Journal of the American Statistical Association*, 74(366), 427–431.
- Enders, W. (2014). *Applied Econometric Time Series* (4th ed.). Wiley.
- Hamilton, J. D. (1994). *Time Series Analysis*. Princeton University Press.
- Hurst, H. E. (1951). Long-term storage capacity of reservoirs. *Transactions of the American Society of Civil Engineers*, 116, 770–799.
- Kwiatkowski, D., Phillips, P. C. B., Schmidt, P., & Shin, Y. (1992). Testing the null hypothesis of stationarity against the alternative of a unit root. *Journal of Econometrics*, 54(1–3), 159–178.
- Mandelbrot, B. B., & Wallis, J. R. (1969). Robustness of the rescaled range R/S in the measurement of noncyclic long run statistical dependence. *Water Resources Research*, 5(5), 967–988.
- Said, S. E., & Dickey, D. A. (1984). Testing for unit roots in autoregressive-moving average models of unknown order. *Biometrika*, 71(3), 599–607.
- Tsay, R. S. (2010). *Analysis of Financial Time Series* (3rd ed.). Wiley.

---

## Frequently Asked Questions

### What is the difference between the ADF test and the KPSS test?

The ADF test's null hypothesis is that the series has a unit root, so **failing to reject** is the ambiguous outcome. The KPSS test (Kwiatkowski, Phillips, Schmidt & Shin, 1992) flips the null: it tests **stationarity** against a unit-root alternative. Using them together is standard practice — if ADF rejects and KPSS does not, both tests agree on stationarity; if the reverse, both agree on a unit root; disagreement indicates the sample is uninformative and more data or a different specification is needed.

### Is a low p-value from the ADF test enough to trade a series?

No. Statistical significance is necessary but not sufficient. A trading strategy needs the half-life to be short relative to your holding horizon, transaction costs to be small relative to the typical reversion amplitude, and the process to remain stable out of sample. A p-value of 0.001 on a series with a 200-day half-life and 5 basis points of typical reversion is not a strategy — it is a statistical curiosity.

### Can I use the Hurst exponent alone?

You can, but you probably shouldn't. The Hurst exponent is noisy in small samples, sensitive to the estimator you choose, and gives no explicit test statistic against a null. It is best used as a corroborating diagnostic alongside the ADF test rather than a standalone screen. If Hurst says 0.42 and ADF says p = 0.02, the story is coherent. If Hurst says 0.42 and ADF says p = 0.6, something is off.

### How does the half-life relate to the Ornstein–Uhlenbeck reversion speed?

The continuous-time OU process $dx_t = \theta(\mu - x_t) dt + \sigma dW_t$ has half-life $t_{1/2} = \ln(2) / \theta$. The discrete AR(1) approximation gives $\rho = e^{-\theta \Delta t}$ where $\Delta t$ is the sampling interval. Estimating $\rho$ from a daily series and converting gives an implied $\theta$ that matches the OU calibration to within sampling error.

### Do these tests work for intraday data?

The mathematics is unchanged, but two practical issues arise. First, microstructure noise (bid–ask bounce, discreteness) introduces spurious short-horizon anti-persistence — a Hurst well below 0.5 that has nothing to do with genuine mean reversion. Second, intraday seasonality (opening auction, lunch dip, closing rally) violates the stationarity of the innovations. Both effects should be modelled or filtered out before testing.

### What lag length should I use in the ADF test?

Use software defaults (AIC or BIC selection) unless you have a reason to override. If you do fix the lag manually, start with Schwert's rule as an upper bound and reduce until the residuals show no significant autocorrelation. Choosing the lag to minimise the p-value is data snooping and invalidates the test.
