# Claim contract

| User phrase | Estimand | Method | Required evidence | Refusal condition |
|---|---|---|---|---|
| observed failure proportion | failures / canonical cohort | Wilson interval | at least 30 units | cohort below floor |
| failure probability by a horizon | \(1-\hat S(t)\) | Kaplan–Meier + Greenwood/log-log CI | horizon, follow-up, at least 30 units | cohort below floor |
| B10 at use conditions | 10th all-cause lifetime percentile | accelerated right-censored Weibull MLE | stress segments and at least 5 failures | insufficient events or singular fit |
| compare two groups | survival-distribution difference | log-rank test | both arms at least 30 units and 5 failures | either arm below floor |
| anomalous source | one-sided proportion contrast to pooled rest | Fisher exact + BH correction | at least 3 levels, 30 units each | insufficient levels |
| measurement drift | median-centered linear trend | slope CI and candidate breakpoint | at least 20 points and 14 days | insufficient points/span |

The configured floors are conservative product rules, not universal guarantees of statistical power. Every result reports the observed sample and the exact floor.

## What the project does not claim

- Synthetic data only; no real hardware has been validated.
- Not suitable for production reliability or warranty decisions.
- Weibull and acceleration assumptions must be validated for a real failure mechanism.
- An association with a revision does not establish that the revision caused the change.
- The v1 station trend does not fully adjust for changing part mix and says so in its caveat.
- Numerical grounding verifies provenance and transformations, not the truth of a model assumption.
- Namespace isolation is shared-cluster workload isolation, not a secure multi-tenant compute platform.
