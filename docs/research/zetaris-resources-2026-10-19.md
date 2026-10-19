# New HackOS resources: Zetaris guides and "5 GitHub repos" (read 19 Oct 2026)

On 16 Oct the organisers added 24 Zetaris links and one Builder Resources article to the HackOS
Resources hub. Most of the Zetaris items are links into Zetaris's public getting-started site
(zetaris.github.io/getting-started). This note records what in them affects our build. Our setup
(our own Zetaris 2.4.3 bundle on AWS EC2, four Postgres sources, REST access) is unchanged.

## What we take into the build

From "SQL gotchas and limits" (the Lightning SQL Companion, live-tested on Zetaris 2.4.3.1):

1. **Send a multi-table `COMPILE USL` as one statement.** A runner that splits SQL on semicolons
   breaks it. Our adapter must send each statement whole, never split a script by `;`.
2. **Replacing a USL model clears activation.** After `UPDATE USL … AS <JSON>` the next `SELECT`
   fails with "table is not activated" until `ACTIVATE USL TABLE` runs again. Our setup script
   re-activates every table after any model change.
3. **`DESCRIBE BY` text** accepts letters, digits, spaces, `_ . - ,` only. Parentheses, slashes and
   colons fail. (We hit the colon case on 14 Oct.)
4. **Data-quality rules (`REGISTER DQ`):** no window functions and no row alias in the rule
   expression; generated rule names follow the column name, so read `LIST DQ USL` instead of
   guessing. Cross-table checks stay as plain join queries.
5. **Check counts against the source.** The guide calls this non-negotiable: `COUNT(*)` through
   Zetaris against the same count taken directly. Our 14 Oct test already did this for all four
   sources and five metrics; the evaluation keeps it as a setup check.
6. **`CACHE TABLE` is a session cache** and `CREATE OR REPLACE` on a view drops it. Useful for the
   anomaly scanner's repeated metric queries if they turn out slow; not relied on.
7. **Self-joins on `UNION ALL`/`explode()` views fail** (MISSING_ATTRIBUTES). This affects REST and
   JSON views, not our JDBC tables, but prefer window functions over self-joins in generated SQL
   anyway.

From "Connecting Cursor to Zetaris": Zetaris's repository has a root `AGENTS.md` with connection,
SQL and permission rules for coding agents (read-only SQL first, one statement per call, keep
multi-table `COMPILE USL` intact, ask before creating objects). Our build tasks give Cursor the same
rules in the issue body. It also confirms the REST path we use (API key from the GUI, organisation
ID, OpenAPI spec fetched with Basic auth).

## Checked and not needed

- **"Install on AWS" (managed cluster):** a Zetaris Cloud Gateway feature that builds an EKS
  cluster through a CloudFormation stack (recommended region us-west-1, "Mini" size of two nodes,
  about 30 minutes to provision, billed to our AWS account, with networking and storage that cost
  money until the stack is deleted). Our single EC2 server with the Docker bundle is cheaper and
  already loaded with our data. No change.
- **Shared event instance:** the Cursor guide mentions team prefixes on an event instance. We run
  our own, so this does not apply; if the organisers require the shared instance, our REST adapter
  only needs a new URL, organisation ID and key.
- **PokéAPI, REST source, Parquet/CSV and open-data USL recipes:** examples for other data shapes.
  Our sources are Postgres over JDBC.
- **"5 GitHub Repos to Build Faster at Your Next Hackathon"** (Builder Resources, a 7-page image
  PDF): Appwrite, Supabase, PocketBase, Coolify and n8n. Generic backend, deployment and automation
  tools with no sponsor link. Our stack (FastAPI, Postgres behind Zetaris, Docker Compose) already
  covers what they offer, and adding one would cost time without scoring anything. Not used.
