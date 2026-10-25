<!-- Investigator, rewrite after a value check (Sprint 11d). Does: maps the filters to stored values.
Must not: change the measure, window, baseline or output columns. -->
The INPUT also has `previous_sql`, which matched no records (`previous_result`), and `value_check`:
a query of the values actually stored in the columns it filtered on, with its rows. Rewrite the
measurement so that every filter uses a stored value (map names to the stored codes, spelling and
case; use the column, and join the table, that holds this kind of segment). Keep the same measure,
window and baseline, and the same output columns.
