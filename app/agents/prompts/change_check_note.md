This is the change check. Besides `value` and `baseline`, return two more columns so the change can
be compared with normal variation and its sample judged:
- `spread`: the standard deviation of the same measure across the baseline window cut into periods
  as long as the window (for a one-day window, the day-by-day values; for a one-month window, the
  month-by-month values). NULL when the baseline holds fewer than two such periods.
- `n`: the number of records (orders, reviews, deliveries, ...) behind the measure in the window.
