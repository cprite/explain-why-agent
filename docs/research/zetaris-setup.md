# Zetaris setup note

Written 2026-10-13, Alan (researcher). Built from Zetaris's own material only: the
`zetaris/getting-started` GitHub repo (fetched directly from `raw.githubusercontent.com`,
commit as of today), `kbase.zetaris.com`, and the Data Day workshop recording's own notes
(`research/workshops/data-day-notes.md`), used only for the one claim the written docs don't
cover. Every command/SQL block below is quoted verbatim from the named file. Nothing is filled
in from general knowledge — where the material doesn't say, it's marked **Not found**.

---

## 1. Install: Docker distribution — steps, requirements, architecture

**Source:** `docs/install/updated_zetaris_installation_guide.md` (dated 24 Sept 2026, in the
getting-started repo), corroborated by `START-HERE.md`.

### Architecture — confirmed x86-only, no ARM64 build

Quoted directly from the guide's requirements table (§3.1):

> | Requirement | Guidance for this bundle |
> |---|---|
> | **Architecture** | The supplied Zetaris images are **amd64**; Apple Silicon requires emulation |

And from the AWS path (§4.2), the only AMI offered is explicitly x86:

> | AMI | Canonical Ubuntu Server 24.04 LTS, **x86_64** |

**Conclusion for our setup: no ARM64 build exists.** The Raspberry Pi 5 that runs our agents
cannot host Zetaris — it's ARM64 Linux with no Rosetta-equivalent amd64 emulation layer (Apple
Silicon's path, "enable supported amd64 acceleration," is a macOS-specific feature). This
confirms the Data Day notes' inference with a direct quote. Candidates per the notes: a Mac/PC
with Docker Desktop, an x86 box on the home network, or the AWS path below.

### Local Docker Compose — requirements and steps

Requirements table (§3.1), quoted:

> | Requirement | Guidance for this bundle |
> |---|---|
> | Docker | Docker Engine 25 or later is recommended by the preflight script; daemon must be running |
> | Compose | Use the `docker compose` plugin; this guide was tested with Compose 5.5.1 |
> | Memory | 8 GB available to Docker recommended; preflight fails below 6 GB |
> | CPU | 4 CPUs available to Docker recommended |
> | Disk | At least 15 GB free for the installation; allow additional space for datasets and logs |
> | Network | Outbound access to the image registry and the data sources you will query |

Components (§2, "What is being installed"):

> | Component | Purpose |
> |---|---|
> | `postgres` | Metadata and audit databases, plus bundled sample data |
> | `init` | Initialises shared volumes and encryption keys; exits successfully when finished |
> | `driver` | Zetaris query engine |
> | `api` | Application API |
> | `ui` | Browser interface |
> | `bootstrap` | Creates the initial organisation, administrator and configured sample data; exits when finished |
> | `ai-datasteward` | AI data service; included in this Compose configuration |

Steps, quoted verbatim (§3.2–3.4, §5):

```bash
unzip zetaris-platform.zip
cd zetaris-platform
docker version
docker compose version
docker login zetarishackathon.azurecr.io
./preflight.sh
```

Then edit `.env` (admin email/password/org; `UI_PORT` "3000"; `ALLOWED_ORIGINS`/`GUI_URL`
`http://localhost:3000`; `ZSPARK_DRIVER_MEM` "2g", `ZSPARK_DRIVER_CORES` "2"), then:

```bash
chmod 600 .env
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose ps --all
docker compose logs --tail=80 driver api bootstrap
./verify.sh
```

> Allow about 30–45 minutes for a first installation... In testing on an Apple Silicon laptop
> with the images already downloaded, the first startup finished in under four minutes.

Then open `http://localhost:3000`, sign in (default shipped login per the bundle README:
`admin@zetaris.com` / `Zetaris1@` — "change that password immediately"), and in the SQL
Editor run `SELECT 1 AS one;` — "Expect one row with value `1`."

**Download path** (§2): Start at `zetaris.com/cloud` → "Start Free" → sign in/register (or
`cloud.enterprise.zetaris.com/register` directly) → the "Run locally" page
(`cloud.enterprise.zetaris.com/dashboard/download`) → download `zetaris-platform.zip` + the
registry sign-in command shown there. "Move the zip out of Downloads before unpacking it."

**Ports used elsewhere in the docs:** UI `localhost:3000`; local JDBC default
`jdbc:zetaris:lightning@localhost:10000`; local REST default `http://localhost:8888/api/v1.0`;
port **8889 is explicitly an internal login route, not for direct use** —
`docs/connections/cursor-connection.md` §6.3: "Do not call port 8889 on a local instance."

### AWS path (if a local x86 box isn't available)

From §4, quoted: `m7i-flex.large` (2 vCPU, 8 GiB), Ubuntu 24.04 LTS x86_64, `ap-southeast-2`,
40 GiB gp3 disk — "about $1.04 for an eight-hour session, paid from AWS Free plan credits."
Eligibility caveat, quoted exactly: "AWS accounts created on or after 15 July 2025 have a Free
plan whose eligible instance types include `m7i-flex.large` (8 GiB)... Accounts created before
that date have the older free tier, which only covers 1 GiB `t2.micro`/`t3.micro` instances;
those accounts need a paid instance such as `t3.xlarge`." The Free plan itself "lasts six months
or until the credits are used up, whichever comes first," and new-account credits "start at
$100, with up to $100 more earned through qualifying activities; a $200 balance is not
automatic." Access the installed UI over an SSH tunnel (`-L 127.0.0.1:3000:127.0.0.1:3000`).

---

## 2. Registering a Postgres database as a source

### The syntax, quoted verbatim

`docs/guides/zetaris-lightning-sql-commands.md` §4.1, `CREATE DATASOURCE`:

```sql
CREATE DATASOURCE <name> [DESCRIBE BY '<desc>'] OPTIONS (key 'value', …)
```

> Registers an external source (JDBC, Cassandra, MongoDB or DynamoDB, detected from the
> options) after testing the connection. **Privileges:** Administrators only.

**Example** (same file, same section):

```sql
CREATE DATASOURCE crm_pg DESCRIBE BY "PostgreSQL" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://crm-db.example.com:5432/crm",
  username "datathon",
  password "changeme",
  fetchsize "1000"
)
```

Then import the tables (§4.2/4.3):

```sql
REGISTER DATASOURCE TABLE "customers" FROM crm_pg
REGISTER DATASOURCE TABLES FROM crm_pg   -- or: imports every table
```

A read-only way to inspect an **unregistered** source first (§4.8, "Only JDBC sources are
supported"):

```sql
LIST DATABASE TABLES OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://crm-db.example.com:5432/crm",
  username "datathon",
  password "changeme"
)
```

### This is not a tested worked example — flagged explicitly, from four separate places in the repo

The `crm_pg` example above is the command reference's own stated convention: §2.3 labels every
example object, including `crm_pg`, **"illustrative only."** It is not SQL anyone has run
against a live instance in this repo. Confirmed independently four ways:

1. `open_data/manifest.json` — every registered source is `kind: rest` or `kind: filestore` (or
   `usl`). There is no `jdbc`/postgres-kind entry anywhere in the manifest that
   `scripts/onboard.py` reads.
2. `docs/guides/recipe-readiness.md`, "Leave these for later" table: **"SQL databases, logs,
   PDFs and other planned recipes | Not ready for onboarding."**
3. `docs/plans/FUTURES.md`, the priority table: **"2 | SQL RDBMS | 📋 Planned |
   [recipes/02-sql-rdbms.md] | Self-hosted via docker compose, no external account needed —
   establishes the JDBC `CREATE DATASOURCE` pattern independent of any API-key story."** —
   status is Planned, not Done; compare row 0/1 (Parquet/CSV, REST), both marked ✅ Done.
4. The plan file itself, `docs/plans/recipes/02-sql-rdbms.md` — status **"📋 Planned"**, every
   work item an unchecked `[ ]`, including literally: *"Confirm `CREATE DATASOURCE` JDBC syntax
   against Zetaris docs... and verify against a live instance."* That confirmation has not
   happened yet, by the repo's own account.

**What that plan file does recommend, for when it's built** (quoted): self-hosted PostgreSQL
via the official `postgres` Docker image, loaded with **Chinook** (MIT, digital-media-store
schema) and/or **Pagila** (PostgreSQL License, DVD-rental, join-heavy) sample schemas — a draft
Chinook DDL excerpt is included (`Artist`/`Album` tables with a foreign key) but the
docker-compose loader script itself doesn't exist in the repo yet.

**What does exist and is tested:** a plain Postgres *connectivity* check — not a Zetaris
registration — `scripts/ping_postgres.py` / `.ts`. From `scripts/HOWTO.md`: "The script
authenticates and runs `SELECT 1`, reports elapsed time, then closes the connection... Connection
and server-side query timeouts are 10 seconds." It reads `PGHOST`, `PGPORT`, `PGDATABASE`,
`PGUSER`, `PGPASSWORD`, `PGSSLMODE` from `.env.local`. This confirms a Postgres server is
reachable before you'd point `CREATE DATASOURCE` at it — it does not touch Zetaris at all.

**Bottom line for our four Postgres sources:** the SQL syntax above is Zetaris's own
documented, generic syntax (cite it with confidence) — but nobody in this repo has run it
against a live instance, so treat the first real attempt as the thing that needs testing early,
not as a known-working recipe to copy.

---

## 3. Unified Semantic Layer — DDL, worked example, cross-source join

### DDL pattern

Built from the (separately supplied) *Unified Semantic Layer (USL) User Guide* — flagged in
`docs/guides/zetaris-lightning-sql-companion.md` §0 as: **"No dedicated page found in the
Kbase's 'Using Zetaris' index as of 2026-09-23... The supplied 'Unified Semantic Layer (USL) —
User Guide' is, as far as this repo has found, the only documentation for this feature right
now."** (checked the full kbase nav and the SQL Guide's statement list — no USL entry in
either). Treat USL as single-sourced and less independently verifiable than the REST/filestore
material above.

### Worked, repo-verified example

`open_data/usl/sql/02_sic_edgar_usl_create.sql` — a two-table USL (`sic_code`, `company`)
joined by a foreign key, built from two different REST-registered sources (`company_dns` and
`sec_data`/EDGAR). Quoted directly:

```sql
CREATE NAMESPACE IF NOT EXISTS lightning.metastore.usl_demo;

COMPILE USL IF NOT EXISTS sic_edgar_usl DEPLOY NAMESPACE lightning.metastore.usl_demo DDL
CREATE TABLE sic_code (
    sic_code varchar(4) NOT NULL PRIMARY KEY,
    description varchar(200),
    division varchar(1),
    division_desc varchar(200),
    major_group varchar(2),
    major_group_desc varchar(200),
    industry_group varchar(3),
    industry_group_desc varchar(200)
);

CREATE TABLE company (
    cik varchar(10) NOT NULL PRIMARY KEY,
    entity_name varchar(200) NOT NULL,
    sic varchar(4) NOT NULL FOREIGN KEY REFERENCES sic_code(sic_code),
    sic_description_edgar varchar(200)
);
```

...then `UPDATE USL ... SET DESCRIPTION '...'`, `ACTIVATE USL TABLE
lightning.metastore.usl_demo.sic_edgar_usl.sic_code AS SELECT ...` (populating from
`company_dns.sic_codes_raw`), `ACTIVATE USL TABLE ....company AS SELECT ...` (a `UNION ALL` of
seven `sec_data.<company>_submissions_raw` REST tables), and `RUN DQ TABLE
lightning.metastore.usl_demo.sic_edgar_usl.company;` to execute the FK's auto-generated
data-quality rule. Verification status, quoted: **"The lifecycle through Step 4 is confirmed
working (after a null-handling fix, commit `8f18f4f`)."** Expected result after `RUN DQ`,
quoted: `total_records=7, valid_records=7`.

### Can it join across two sources in one query? Yes — with one confirmed limit

Yes, confirmed live: this USL activates data originating from **two different registered
sources** (`company_dns` and `sec_data`) into one semantic model, and the FK join between the
two USL tables (`company.sic → sic_code.sic_code`) runs and passes. Once activated, the model is
"queried like a database with ordinary SQL" (per the Data Day notes) — ordinary `SELECT ... JOIN
...` across the two tables.

**The one open limit, quoted directly from the script's own header:** "whether a FK can target
a table in a different USL... is unconfirmed. This script defines its own copy of `sic_code`
inside `sic_edgar_usl` rather than assuming cross-USL FKs work." So: joining data that
originated from two different *source systems*, within the *same* USL, is confirmed working.
A foreign key reaching *across two separate USL objects* is explicitly not confirmed either way.

**Not yet tested with our actual sources:** since no Postgres source exists in this repo (§2
above), nobody has built or tested a USL over Postgres-backed tables specifically — the pattern
above is confirmed for REST sources only.

---

## 4. Querying from a program: REST vs JDBC

**Source:** `docs/connections/cursor-connection.md` (written for Cursor specifically, but the
connection mechanics are protocol-level, not Cursor-specific) and `docs/connections/README.md`.

### JDBC

- Driver class: `com.zetaris.lightning.jdbc.LightningDriver`.
- URL format: `jdbc:zetaris:lightning@<host>:<port>` — local default
  `jdbc:zetaris:lightning@localhost:10000`.
- Requires: the Zetaris JDBC driver JAR (from the platform download — **not included in the
  getting-started repo**, "The agent will ask you for its location"), a JDK 11+ runtime, and
  from Python, the `jaydebeapi` package (since JDBC is a Java API) — `python3 -m venv .venv &&
  .venv/bin/pip install -r scripts/requirements.txt`.
- Check readiness: `python3 scripts/preflight.py --jdbc --jar <path>`.

### REST

- Base URL: `http://localhost:8888/api/v1.0` (local) or the Cloud URL supplied by organisers.
- Auth: a **bearer API key you create yourself in the Zetaris GUI** — quoted: "the agent cannot
  use REST until you have an API key, and the key is created by the user, not the agent" — plus
  a numeric `X-Org-ID` and a fresh UUID `X-Request-ID` on every request.
- Run SQL: `POST <REST_URL>/sql-editor/sqls/run` with the SQL text (confirmed response shape:
  `{"headers":[...],"data":[[...]],...}`); list sources: `GET <REST_URL>/datasource/datasources`.
- The OpenAPI spec is fetched from the instance itself (not a saved copy), using **HTTP Basic**
  auth (username/password, *not* the bearer key): `curl -s -u "$ZETARIS_USERNAME:$ZETARIS_PASSWORD"
  http://localhost:8888/redoc/docs.yaml -o docs.yaml` — confirmed "HTTP 200, OpenAPI 3.1.0,
  about 280 paths, with both `bearer` and `basic` security schemes."
- Requires only an HTTP client — no JVM.

### Which is simpler from Python: REST

The repo's own decision table (`cursor-connection.md` §3) states it directly: **"No Java
runtime available → Use REST."** JDBC needs a JDK, a driver JAR you must separately obtain, and
`jaydebeapi`; REST needs only the API key and plain HTTP calls. Both reach the same engine and
gave matching results in testing — quoted: "Verified against the local instance: row counts and
integrity checks over REST matched JDBC exactly." Two REST-specific quirks to code around:
**every value comes back as a string** (decimals can appear in exponent form, e.g. `0E-18`), and
REST enforces whatever `limit` you send. Since our planned agent stack is plain Python with no
JVM dependency otherwise, REST is the simpler integration for us specifically.

---

## 5. Can CSV files be a source directly?

**From the workshop (Data Day notes, already flagged there as low-confidence, auto-caption
sourced):** plain CSV upload was not described as a Zetaris mechanism in the 46-minute session;
the one "upload a CSV" aside in the transcript was about a different, unrelated example (an
AI-agent hotspot concept), not Zetaris. Confirmed by re-reading the transcript directly — no
Zetaris-specific CSV-upload flow is described anywhere in it.

**From the written docs — CSV is a supported file *format*, but via cloud storage, not a direct
local upload:**

`docs/guides/zetaris-lightning-sql-commands.md` §5.3 lists CSV among the supported formats:
"CSV, JSON, PARQUET, ORC, DELTA, XML, AVRO, PDF, IMAGE, VIDEO, AUDIO, DOC, TEXT, MARKDOWN, RTF."
The repo's own live-tested, confirmed-working CSV example (`open_data/parquet_csv/sql/
02_noaa_ghcn_create.sql`) uses `FORMAT CSV` with an S3 `PATH`:

```sql
CREATE LIGHTNING DATABASE <logical_datasource_name> DESCRIBE BY "<short description>";

CREATE LIGHTNING FILESTORE TABLE <table_name>
FROM <logical_datasource_name>
FORMAT CSV
OPTIONS (
  PATH "s3a://bucket/prefix/or/file.parquet",
  inferSchema "true",
  header "true",
  isS3BucketPublic "true",
  useS3PathStyleAccess "true",
  s3Endpoint "s3.<region>.amazonaws.com"
);
```
(pattern quoted from `open_data/parquet_csv/HOWTO.md` §1)

**The catch:** every tested CSV example in this repo puts the file in S3 (or an S3-compatible
host, per Foursquare's example). A file that exists only on your laptop is explicitly called
out as **not usable directly**: `updated_zetaris_installation_guide.md` §6 — "A file downloaded
onto your laptop is not automatically visible to the query engine, particularly on AWS." Kbase's
generic "Connecting to your data overview" page separately lists "local/network file drives" as
a valid *File Source* location for the product in general — but nothing in this repo has tested
that path, and every concrete worked example uses S3. **So: CSV is a supported format, but the
confirmed, tested route puts the file in S3 first; registering a CSV straight from a local
filesystem path is not confirmed one way or the other in this repo.**

---

## 6. Limits of the free distribution

**Row/result limits — only two narrow, specific ones found, no general row cap:**

- `PREVIEW DATASOURCE SQL` (Lightning Command Reference §4.7): "Runs native SQL on a datasource
  and returns **up to 10 rows**." A genuine platform limit, but scoped to that one preview
  command only.
- `ZETARIS_QUERY_LIMIT` (`scripts/HOWTO.md`): a **client-side** default of 1000 rows, used by the
  repo's own `query_zetaris.py`/`.ts` helper scripts — "`ZETARIS_QUERY_LIMIT` caps returned rows
  at 1000 by default." This is a helper-script default you can change, not a server-enforced cap.
  REST separately "applies the `limit` you send" (`cursor-connection.md` §3), so the caller
  controls it there too.
- **No general server-side row limit, and no source-count limit, found anywhere in the fetched
  material.** Marked **Not found** rather than assumed absent.

**Expiry / licence terms — confirmed, and in tension with the "free forever" framing:**

`updated_zetaris_installation_guide.md` §2, quoted directly: "You need the platform archive, its
matching `.env`, registry credentials and **a Zetaris licence or evaluation entitlement** covering
your installation... Your use of the platform is governed by your Order with Zetaris. **Without
one, the agreement allows internal evaluation for up to 30 days; it does not grant an ongoing
licence.**" This is the platform's own install guide, not a workshop paraphrase. **Flag: the
Data Day framing was "free forever," but the written install guide's own licence language caps
an un-ordered evaluation at 30 days** — worth confirming directly with the Zetaris HackOS support
channel whether participant accounts get a longer entitlement, since the build window (22–27 Oct)
plus any setup done beforehand could matter against a 30-day clock depending on when the account
was created.

**AWS path's own time/cost box** (not a Zetaris limit, but binds the same installation): the
Free plan "lasts six months or until the credits are used up, whichever comes first," and new
accounts get "$100, with up to $100 more earned through qualifying activities" — not an automatic
$200. The guide's own worked estimate is **~$1.04 for an 8-hour session**, rising to ~$94.87 if
left running for a full 730-hour month — budget and tear down deliberately if using AWS.

**Publishing results — licence scope is split, and only partly confirmed:**

Quoted directly: "The Apache licence in the `getting-started` repository covers the data
recipes only, **not the platform images**." So our own SQL/DDL/recipes can be published under
Apache-2.0 (the repo's own `LICENSE` file) without issue. The platform itself (Docker images,
driver, UI) is not open-source and is governed by the Order/evaluation agreement referenced
above — I could not fetch the full Terms and Conditions text
(`cloud.enterprise.zetaris.com/terms` renders via JavaScript; a plain fetch returned only
"Loading…", and I did not use a browser tool to render it per the "do not sign up or install
anything" instruction, since a ToS page likely requires an account context to view fully).
**The specific question "can we publish a recording/screenshot of a running Zetaris instance in
our submission" is therefore marked Not found** — the install guide's one quoted sentence above
is all that was confirmed; everything beyond it would need a direct question to Zetaris's HackOS
support channel.

---

## Summary of what's confirmed vs. not for our plan

| Question | Status |
|---|---|
| ARM64 build exists | **No** — confirmed amd64-only, twice over (local images, AWS AMI) |
| Postgres `CREATE DATASOURCE` syntax | Confirmed (generic, from the command reference) |
| Postgres *worked, tested* example in this repo | **Does not exist** — confirmed Planned/not-started, four ways |
| USL can join two sources | **Yes**, confirmed live (REST+REST); Postgres-backed USL untested |
| REST vs JDBC for Python | REST is simpler — confirmed by the repo's own decision rule |
| CSV as a direct source | Supported format, but only confirmed via S3; local-file path untested |
| Hard row/source limits | None found beyond two narrow, specific cases |
| Licence expiry | **30 days without a paid Order** — confirm with Zetaris support before relying on "free forever" |
