<!-- Investigator, change check. Does: asks for the spread and record counts with the change check's
SQL. Must not: replace the period-level spread with a per-record deviation. -->
This is the change check. Besides `value` and `baseline`, return two more columns so the change can
be compared with normal variation and its sample judged:
- `spread`: the standard deviation of the same measure across the baseline window cut into periods
  as long as the window (for a one-day window, the day-by-day values; for a one-month window, the
  month-by-month values). NULL when the baseline holds fewer than two such periods. Compute the measure
  per period first; never take the deviation of per-record values (a share's 0/1 flags).
- `n`: the number of records (orders, reviews, deliveries, ...) behind the measure in the window.
- `n_baseline`: the same count in the baseline window.
