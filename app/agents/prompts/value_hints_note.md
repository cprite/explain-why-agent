Tables in `sources` may list `values`: for a text column with few distinct values, every stored
value (most frequent first); for any other text column, the number of distinct values, their case or
format and a few examples. Filter only on stored values. Map each name in the question to the stored
value listed for it: a full name to the stored code, a word written with a hyphen or spaces to the
stored spelling (for example with an underscore), a name to the stored case. Filter on the column
whose values match the kind of segment (a state on a state column, a channel on the column that holds
channels) and join to the table that holds it when needed.
