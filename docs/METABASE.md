# Metabase — Diamond's BI Workshop

Diamond ships with **Metabase** embedded as the chart-building / BI surface.
This doc covers install, config, the save-aware Pattern A architecture,
and ops.

> **TL;DR**: Run `~/.diamond/metabase/metabase.bat /b` once per machine
> session. Open Diamond → **Explore → Metabase Workshop**. Build any
> chart against your active save. Save-switching in Diamond auto-flips
> Metabase's data source.

---

## Architecture — Pattern A

| Layer | Process | Source of truth |
|---|---|---|
| Diamond UI (Next.js) | `localhost:3000` (web/) | Reads typed JSON from FastAPI |
| Diamond API (FastAPI) | `localhost:8000` (uvicorn) | Reads active save's DuckDB |
| **Metabase BI** | `localhost:3000` (Java) ← *wait, port collision?* | |

**Port note**: Diamond's Next.js dev server binds `:3000` and Metabase
also defaults to `:3000`. **Diamond's frontend uses `:3000`**;
**Metabase's iframe target is also `:3000`** in the docs above as a
copy-paste convenience. In practice we keep Metabase on a non-conflicting
port. Default ports below:

| Process | Port |
|---|---|
| Next.js (Diamond UI) | 3000 |
| FastAPI (Diamond API) | 8000 |
| Metabase | **3001** (override `MB_JETTY_PORT` in `metabase.bat` if needed) |

> **Action item**: edit `~/.diamond/metabase/metabase.bat` to set
> `MB_JETTY_PORT=3001` if you've already booked `:3000` for Next.js.
> The Diamond UI's `MetabaseWorkshop` component reads
> `NEXT_PUBLIC_METABASE_URL` if set; otherwise defaults to
> `http://localhost:3000` (which assumes you've moved Next.js to a
> different port). Picking the right binding is up to you — the
> integration just needs them not to collide.

### Pattern A — single Database connection follows the active save

Diamond has one Metabase Database registered (`database_id=1`). Its
`details.database_file` always points at the **active save's** DuckDB
warehouse:

```
~/.diamond/active_save.toml says active = "Building the Green Monster.lg"
   ↓
Metabase Database 1 .details.database_file =
    "C:/Users/.../Building the Green Monster.lg/diamond/diamond.duckdb"
```

When you switch saves in Diamond's UI (`/settings/save`), the
`POST /api/saves/active` handler does three things:

1. Persists the new save name to `~/.diamond/active_save.toml`
2. Updates FastAPI's in-memory `set_active_save()`
3. Calls `repoint_active_save()` in `src/diamond/api/metabase.py`
   which `PUT`s the new path into Metabase's Database 1 + triggers
   schema re-sync

**Schema stability is the load-bearing assumption**: every Diamond save
has the same warehouse schema (L0 → L_REF identical), so Metabase's
field IDs (cards reference these) stay valid across save swaps. Re-sync
just refreshes row counts + fingerprints.

### What this guarantees vs. doesn't

| Behavior | Across save switches |
|---|---|
| Pre-built dashboards (leaderboards, distributions, scatter explorer) | ✓ Identical — schema is the same, only data changes |
| Generic cards (top-N by stat, distribution histograms) | ✓ Same |
| Native SQL queries against semantic tables | ✓ Same |
| Cards filtered by year / level / league_id | ✓ Same (these are save-stable concepts) |
| Cards hardcoded to a specific `player_id` | ✗ Break — IDs aren't stable across saves |
| Cards hardcoded to `team_id` | △ Mostly stable (BOS=4 in standard OOTP saves) but not guaranteed |

**Rule**: build save-agnostic cards in Metabase. Use Diamond's existing
pages (player, roster, movements) for save-specific drill-downs.

### When to use Pattern B instead (multi-save side-by-side)

Pattern A means you can only see one save's data at a time in Metabase.
If you need side-by-side comparison of two saves, opt into Pattern B:

1. Open Metabase admin: `http://localhost:3001/admin/databases`
2. **Add database** → DuckDB engine → point at the second save's
   `<save>/diamond/diamond.duckdb`
3. The new connection becomes `database_id=2`
4. Build cards against either DB explicitly

Pattern A and B coexist — Diamond will continue managing Database 1;
Database 2+ are yours to manage manually.

---

## First-time install (one-time, ~15 min)

### Prerequisites

- Windows (these instructions; macOS/Linux paths differ)
- Disk space: ~1 GB

### 1. Install Java 21

```cmd
winget install Microsoft.OpenJDK.21
```

Installs to `C:\Program Files\Microsoft\jdk-21.0.11.10-hotspot\` by
default. The `metabase.bat` launcher hardcodes this path; if you install
elsewhere edit `JDK_HOME` in the script.

### 2. Download Metabase + DuckDB driver

```cmd
mkdir %USERPROFILE%\.diamond\metabase\plugins
mkdir %USERPROFILE%\.diamond\metabase\data
mkdir %USERPROFILE%\.diamond\metabase\logs

REM Metabase OSS — must match the DuckDB driver's targeted version
curl -L -o %USERPROFILE%\.diamond\metabase\metabase.jar ^
  https://downloads.metabase.com/v0.59.10/metabase.jar

REM DuckDB driver (community-maintained by MotherDuck team).
REM Driver 1.5.2.0 → Metabase 59 + DuckDB 1.5.2 — match your DuckDB
REM Python package version (pyproject.toml duckdb pin).
curl -L -o %USERPROFILE%\.diamond\metabase\plugins\duckdb.metabase-driver.jar ^
  https://github.com/motherduckdb/metabase_duckdb_driver/releases/download/1.5.2.0/duckdb.metabase-driver.jar
```

> **Version matching**: Metabase versions and DuckDB driver versions
> evolve together. Check
> [the driver releases page](https://github.com/motherduckdb/metabase_duckdb_driver/releases)
> when upgrading — the release name format is "Metabase X + DuckDB Y".
> Match your Diamond Python package's DuckDB version (run `python -c
> "import duckdb; print(duckdb.__version__)"`).

### 3. Copy the launcher script

The repo ships `~/.diamond/metabase/metabase.bat` — already in place from
the Pattern A install. If missing, copy from
`docs/templates/metabase.bat`.

### 4. First boot

```cmd
%USERPROFILE%\.diamond\metabase\metabase.bat /b
```

Waits ~30 seconds, then Metabase is up at `http://localhost:3001`
(or `:3000` if you didn't change the port).

### 5. First-run setup (web UI, one time)

Open the Metabase URL. The setup wizard prompts for:

- **Admin user** — pick a strong password
- **Initial database** — choose **DuckDB**, fill in:
  - Display name: `Building the Green Monster` (or your active save's name)
  - Database file: full path to your active save's DuckDB
    (e.g., `C:\Users\chris\Documents\Out of the Park Developments\OOTP Baseball 27\saved_games\Building the Green Monster.lg\diamond\diamond.duckdb`)
  - **Read-only**: ✓ check this
- **Anonymous tracking**: uncheck (Diamond's launcher disables it via
  env vars regardless)

Initial sync takes ~30 seconds. All ~220 tables are visible after that.

### 6. Save credentials for the save-switch hook

Diamond's `repoint_active_save()` needs Metabase credentials so it can
auth into the API on save switches. Create
`~/.diamond/metabase_credentials.toml`:

```toml
email = "your-admin-email@example.test"
password = "your-strong-password"
```

This file is gitignored. Diamond reads it, posts to Metabase's
`/api/session`, caches the token at `~/.diamond/metabase_session.txt`,
and re-auths automatically on token expiry.

### 7. Test the integration

```cmd
REM Diamond's API + UI are presumed already running
curl -X POST http://localhost:8000/api/saves/active ^
  -H "Content-Type: application/json" ^
  -d "{\"save_name\":\"Building the Green Monster.lg\"}"
```

Check Metabase admin: `http://localhost:3001/admin/databases/1` —
`database_file` should point at the BTGM warehouse. Switch saves and
the path updates automatically.

---

## Daily ops

### Starting Metabase

```cmd
~/.diamond/metabase/metabase.bat /b
```

Detached, logs to `~/.diamond/metabase/logs/metabase.log`. Boot time
~30s. Stays up across browser refreshes; only restart on machine
reboot or Metabase upgrade.

### Stopping Metabase

```cmd
REM Find the PID
tasklist /fi "imagename eq java.exe"
REM Kill it
taskkill /PID <pid> /F
```

Or close the Diamond Metabase window (if launched in foreground).

### Don't run `diamond ingest` while Metabase has the DB open

Metabase's read-only ODBC connection holds a brief lock during query
execution. Most of the time it's released; under heavy use it stays
held. `diamond ingest` opens the warehouse for write — locks collide.

**Easy rule**: stop Metabase before ingest, start after. Or run ingest
overnight when Metabase is closed.

### Checking sync status

```bash
curl -s http://localhost:3001/api/database/1 \
  -H "X-Metabase-Session: $(cat ~/.diamond/metabase_session.txt)" \
  | jq '.initial_sync_status, .details.database_file'
```

### Forcing a re-sync (e.g., after a non-Diamond change)

```bash
curl -X POST http://localhost:3001/api/database/1/sync_schema \
  -H "X-Metabase-Session: $(cat ~/.diamond/metabase_session.txt)"
```

---

## Working with Claude / AI-assisted dashboards

Metabase's REST API is comprehensive, so Claude can build, edit, and
delete cards + dashboards programmatically. Workflow:

1. You: "Build me a dashboard showing rookie of the year candidates"
2. Claude: writes MBQL specs in `diamond/metabase/dashboards/*.yaml`,
   POSTs to Metabase API
3. Dashboard appears in Metabase, viewable in the embedded Workshop
4. You can edit it interactively in Metabase if you want to tweak

Future v2 plan (deferred): a `diamond metabase deploy` CLI subcommand
that reads YAML specs and syncs them to Metabase. Source-controlled
dashboards. (Currently dashboards live only in Metabase's H2 metadata
DB.)

---

## Safety / threat model

This is a **single-user local** deployment. Configuration:

| Hardening | Setting |
|---|---|
| Bind to localhost only | `MB_JETTY_HOST=127.0.0.1` (in `metabase.bat`) |
| Telemetry off | `MB_ANON_TRACKING_ENABLED=false` |
| No update phone-home | `MB_CHECK_FOR_UPDATES=false` |
| Read-only DB | Set in Metabase admin → Database 1 details |
| Sample content skipped | `MB_LOAD_SAMPLE_CONTENT=false` |

Realistic threat model: this Metabase instance is reachable only from
your laptop's localhost. Worst case is "Metabase has a bug and crashes."
The data is OOTP video game stats — no PII, no financial data.

For a comprehensive safety checklist (relevant if you ever expose Metabase
externally — don't), see the previous CVE history thread in DECISIONS.md
D31.

---

## Troubleshooting

### "Cannot open file" / "IO Error" in Metabase log

The DuckDB file path in Database 1 is wrong. Either:
- The active save was renamed/deleted out from under Metabase
- Diamond's save_dir convention drifted (Pattern A wiring should
  prevent this — file a bug if it happens)

Fix: open Metabase admin → Database 1 → Settings → update file path
manually, or POST to `/api/saves/active` to retrigger Pattern A.

### Workshop iframe shows "can't connect"

Metabase isn't running, or it's bound to a different port than the
Workshop component expects. Check:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3001/api/health
```

Should print `200`. If `000`, Metabase is down. Start it via `metabase.bat /b`.

If you're using a different port, set `NEXT_PUBLIC_METABASE_URL` in
`web/.env.local`:

```
NEXT_PUBLIC_METABASE_URL=http://localhost:3001
```

Restart Next.js dev server.

### Save switch succeeds but Metabase still shows old data

Likely the `sync_schema` call landed but Metabase hasn't refreshed
fingerprint cache for the new file. Try:

1. In Metabase admin → Database 1 → click "Sync database schema now"
2. Or re-trigger via curl:
   ```bash
   curl -X POST http://localhost:3001/api/database/1/sync_schema \
     -H "X-Metabase-Session: $(cat ~/.diamond/metabase_session.txt)"
   ```

### Credentials file is missing — save-switch logs say "Metabase running but credentials missing"

Create `~/.diamond/metabase_credentials.toml` per the install steps.
Diamond can't auth without it; save switches still succeed but
Metabase isn't repointed.

### "Database 1 not found"

Means Metabase's Database #1 was deleted. Re-run the first-run setup
flow (admin UI → Add database). Or, manually: POST `/api/database`
with the BTGM connection details, note the new `id`, update
`METABASE_DATABASE_ID` constant in `src/diamond/api/metabase.py`.

---

## Why Metabase, not Power BI / SQL Server / custom

See DECISIONS.md D31 for the full reasoning. Short version:

- **Power BI** would require either Azure Embedded ($) or "publish to
  web" (cloud upload, breaks D16 local-first)
- **SQL Server warehouse** would lose D2 per-save portability + D27
  freeze model
- **Custom Vega-Lite chart builder** is ~6 days of work and doesn't
  beat Metabase for general BI
- **Metabase** is free, self-hosted, embeds in iframes, talks to
  DuckDB via the community ODBC-style driver, and gives Diamond's
  user a full-featured chart-building surface inside the existing app
