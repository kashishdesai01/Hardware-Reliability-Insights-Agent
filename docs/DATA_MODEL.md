# Data model and reliability physics

## Statistical observation

One `test_episode` is one independent lifetime observation for one non-repairable unit under one protocol. A `test_run` is a constant-stress segment inside that episode. `unit_outcome` contains exactly one terminal observation per valid episode:

- `event_observed = true`: an exact failure time with a failure mode.
- `event_observed = false`: a right-censored time; the true lifetime is known only to exceed the observed duration.

Malformed source records are captured in `ingestion_issue` and excluded explicitly. They are not allowed to weaken canonical identity or duration constraints.

## Weibull model

For shape \(\beta\) and scale \(\eta\):

\[
f(t)=\frac{\beta}{\eta}\left(\frac{t}{\eta}\right)^{\beta-1}
e^{-(t/\eta)^\beta},\qquad
S(t)=e^{-(t/\eta)^\beta}
\]

The censored likelihood is:

\[
\log L = \sum_{i:\delta_i=1}\log f(t_i) +
\sum_{i:\delta_i=0}\log S(t_i)
\]

The B10 lifetime is \(\eta[-\log(0.9)]^{1/\beta}\). Parameter fitting occurs in log space; confidence bounds are calculated from the observed-information covariance and the delta method.

## Acceleration

Temperature is converted to Kelvin. With activation energy \(E_a=0.7\,eV\), Boltzmann constant \(k\), and voltage exponent \(n=3\):

\[
AF_T=\exp\left[\frac{E_a}{k}\left(\frac{1}{T_{use}}-\frac{1}{T_{stress}}\right)\right]
\]

\[
AF_V=\left(\frac{V_{stress}}{V_{use}}\right)^n,\qquad AF=AF_TAF_V
\]

Each stress segment contributes equivalent use-condition exposure \(AF_j\Delta t_j\). Episode exposure is their sum. Humidity is recorded as a covariate but is not part of the v1 acceleration model.

## Competing risks

The generator draws an independent candidate use-condition lifetime for each failure mode and records the first cause reached by accumulated equivalent exposure. Other modes are competing events. V1 exposes all-cause lifetime estimates; it does not present a cause-specific B10 as the population B10.

| Failure mode | β | Interpretation |
|---|---:|---|
| infant mortality | 0.6 | decreasing hazard |
| firmware hang | 1.0 | constant hazard |
| dielectric breakdown | 1.3 | mild wear-out |
| connector wear | 2.4 | wear-out |
| solder joint crack | 3.5 | strong wear-out |

The seed is calibrated to 60–75% censoring. `dataset_manifest` records the actual fraction, seed, generator version, planted truth, and counts.

## Planted signals and dirty input

Generator version 1.1 makes the four documented effects recoverable even in the 2,000-unit smoke profile: `LOT-0042` uses a 0.55 solder-joint scale multiplier, `SUPPLIER-03` uses a 0.30 infant-mortality scale multiplier, and post-2025-01-01 revision C of `PN-4471` uses a 6.0 connector-wear scale multiplier. `STATION-007` receives a slow additive contact-resistance bias after 2025-03-01.

Duplicate source serials, missing measurement sets, inverted run timestamps, and a negative duration are written to `ingestion_issue`. The invalid records are excluded from canonical analysis rather than inserted by weakening primary keys, foreign keys, or duration constraints.
