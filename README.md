# BIM360 Photo Fetcher

This script downloads BIM360 attachment files listed in Snowflake and uploads them to Azure Blob Storage.

This repository now also includes a web app (`app.py`) where users can:

- choose a project
- search issues in that project
- filter by issue status
- filter by root cause
- filter by company
- page through result lists
- open images in split view from the issue list
- open an issue detail page and drill down to attachments/images
- see project counters (total issues and total attachments)

## What It Does

- Queries Snowflake for attachment metadata:
  - `attachment_url` (`COALESCE(original_url, url_without_ticket, blobstore_url)`)
  - `file_name`
  - `issue_id`
  - `project_id`
- Downloads public attachment URLs directly.
- Uploads files to Azure Blob Storage.
- Skips blobs that already exist.
- Writes logs to console and `fetch_photos.log`.

## File Mapping in Blob Storage

Each uploaded file is stored as:

`<project_id>/<issue_id>/<file_name>`

Container name is controlled by `AZURE_BLOB_CONTAINER` (default: `clasicfieldphoto`).

## Prerequisites

- Python 3.9+
- Access to Snowflake with keypair credentials
- Azure Storage account connection string with write access to the target container

## Python Dependencies

Install required packages in your virtual environment:

```powershell
pip install snowflake-connector-python azure-storage-blob python-dotenv
```

## Environment Variables

Set these in your shell or `.env` file:

Required:

- `AZURE_STORAGE_CONNECTION_STRING`

Optional (defaults are in script):

- `AZURE_BLOB_CONTAINER`
- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_USER`
- `SNOWFLAKE_ROLE`
- `SNOWFLAKE_WAREHOUSE`
- `SNOWFLAKE_DATABASE`
- `SNOWFLAKE_SCHEMA`
- `SNOWFLAKE_PROJECT_ID`
- `SNOWFLAKE_JKS_PATH` (default: `snowflake1(1).jks`)
- `SNOWFLAKE_JKS_ALIAS` (default: `snowflake`)
- `SNOWFLAKE_JKS_PASSWORD` (required)
- `SNOWFLAKE_JKS_KEY_PASSWORD` (optional; defaults to `SNOWFLAKE_JKS_PASSWORD`)
- `SNOWFLAKE_AZURE_SAS_TOKEN` (optional; set when required by Snowflake credentials)

## Running

From the project folder:

```powershell
python fetch_photos.py
```

## Web App

Web-appen kjorer uten aktiv innloggingsgate i Flask.

### Tilgang

- Ja, appen er apen for alle som kan na URL-en (ingen login i app-koden).
- Lokal kjoring: alle med tilgang til maskinen/nettverket der appen eksponeres kan bruke den.
- Azure App Service: appen er offentlig dersom du ikke har satt opp plattform-beskyttelse.
- Besluttet tilgangsmodell: autentisering styres pa plattformniva (Azure App Service Authentication/Authorization).
- Brukere ma ha tilgang til Entra-gruppen `NO-BIM30-EXPLORER` for a fa tilgang til appen.
- For a begrense tilgang, bruk en eller flere av disse:
  - App Service Authentication/Authorization (Microsoft Entra ID)
  - Access Restrictions (IP allowlist)
  - Private Endpoint/VNet-integrasjon

### Status (drift)

- Autentisering: plattformniva (Azure App Service Authentication/Authorization).
- Tilgangskrav: bruker ma vaere medlem av Entra-gruppen `NO-BIM30-EXPLORER`.
- Flask-appen har ingen intern login-gate; tilgang styres utenfor app-koden.
- Anbefaling: behold Access Restrictions eller Private Endpoint i tillegg ved produksjonsdrift.

Install dependencies:

```powershell
pip install -r requirements.txt
```

Start the app:

```powershell
python app.py
```

Then open:

`http://127.0.0.1:8000`

### HTML App Documentation

#### App structure

- `app.py`: Flask routes, Snowflake queries, Azure Blob preview URLs.
- `templates/base.html`: shared HTML layout and CSS.
- `templates/index.html`: main page for project selection, issue list, filters, split image panel.
- `templates/issue.html`: issue detail page and full attachment gallery.

#### Main page behavior (`/`)

- Project-first flow:
  - User selects project in searchable project input.
  - Issue search and filters are disabled until a project is selected.
- Issue filters available per selected project:
  - free-text issue search (`q`)
  - status (`status`)
  - root cause (`root_cause`)
  - company (`company`)
- Auto-submit behavior:
  - selecting project submits automatically
  - changing status/root cause/company submits automatically
- Result list includes pagination and a Bilder link for split image panel.

#### Query parameters used by UI

- `project_pick`: visible project input value (`<project_name> | <project_id>`)
- `project_id`: resolved project id used by backend queries
- `q`: issue search text
- `status`: selected status filter
- `root_cause`: selected root cause filter
- `company`: selected company filter
- `page`: pagination index (1-based)
- `issue_id`: selected issue for split image panel

#### Data sources and column mapping

- Main issue/filter source: `VW_ISSUES_ENRICHED`
  - status filter uses `status`
  - root cause filter uses `root_cause_name`
  - company filter uses `company_name`
- Attachments/counters source: `BIM360_ATTACHMENTS`

#### Session behavior

- The app keeps last selected `project_id` in session for follow-up filtering requests.
- A fresh load of `/` still starts as project-first (no implicit filter run).

#### Split image panel vs detail page

- `Bilder` in issue table opens images in split panel on main page.
- `/issue/<project_id>/<issue_id>` shows full issue detail and attachment list.

#### Restart note during development

- The app runs with `use_reloader=False`.
- After code/template changes, restart manually:

```powershell
python app.py
```

#### If a filter dropdown looks empty

1. Confirm a project is selected first.
2. Hard refresh browser (`Ctrl+F5`).
3. Restart the app (`python app.py`) to ensure latest code is loaded.
4. Verify the selected project actually has values for that filter field.

Notes for image preview:

- The issue detail page attempts to show images from Azure Blob based on path: `<project_id>/<issue_id>/<file_name>`.
- If files are not already uploaded to Blob (via `fetch_photos.py`), only source links may be available.

Web app query behavior:

- Uses `VW_ISSUES_ENRICHED` for project list, issue list, status filter values, and issue details.
- Uses `BIM360_ATTACHMENTS` for attachment rows and per-issue attachment counts.
- Default page size is 50 rows per page; override with `WEB_PAGE_SIZE` in `.env`.

Snowflake authentication behavior:

- Uses keypair authentication from a Java keystore (`.jks`) file.
- Private key is loaded from alias `snowflake` unless `SNOWFLAKE_JKS_ALIAS` is overridden.
- Default Snowflake user is `NOSYS_ISSUES_KEYPAIR`.
- Requires `pyjks` in the runtime environment: `pip install pyjks`.
- On Windows, `pyjks` may require Microsoft C++ Build Tools because of a transitive dependency.

Expected flow:

1. Script authenticates to Snowflake with keypair credentials.
2. Attachment metadata is read from Snowflake.
3. Attachments are downloaded directly from public URL fields.
4. Files are uploaded to Blob storage.
5. Summary is logged with uploaded/skipped/failed counts.

## Endringslogg (2026-09-07 til 2026-09-08)

### 2026-09-07

- La til nye filter i hovedlisten: `issue_type` og `location_path`.
- La til visningsmodi i hovedvinduet: `Bilder`, `Comments` og `History` i split-panel.
- Forbedret uthenting/visning av comments og history med robust feltoppslag (inkludert case-variasjoner).
- Byttet detaljvisning til URL-basert faneskifte (`view=attachments|comments|history`) for mer stabil navigasjon.
- Gjennomfort flere layout-fikser i split-view:
  - fjernet sticky-overlapp
  - fikset klikkbarhet i panelomrade
  - utvidet hovedlayout for mindre horisontal scrolling
  - fjernet panel-toolbar som ikke ga verdi i praksis
- La til chat-lignende visning av comments i stedet for ra JSON i:
  - hovedpanel (`/`)
  - detaljside (`/issue`)

Relevante commits:

- `73be9e7` Add issue type/location filters and comments/history tabs
- `48394cb` Show comments/history in split panel on main issue list
- `74389b4` Fix split panel comments and history rendering
- `ee66ede` Fix issue detail view buttons
- `c9d3106` Fix split panel overlap in issue list
- `6a8e96a` Keep split panel header visible
- `7c5da6f` Remove sticky overlap in split issue panel
- `00eb997` Always show split panel toolbar
- `8209e88` Fix split panel clickability and overlap
- `7d943c4` Remove split panel toolbar and widen main layout
- `7d18714` Render issue comments as chat bubbles

### 2026-09-08

- Gjorde issue description klikkbar i hovedlisten og aapner detaljside i ny fane/vindu.
- Endret detaljnavigasjon til query-basert rute for robusthet:
  - ny rute: `/issue?project_id=...&issue_id=...`
  - beholdt path-rute med `path`-parameter som fallback
- Fikset `Not Found`/`Bad Request` ved comments-visning for saker med spesialtegn i `issue_id`.
- Normaliserte nøkler i issue-rad (`upper/lower/original`) for aa redusere casing-relaterte datatap i detaljvindu.

Relevante commits:

- `34c4291` Link issue description to detail view
- `6dd544b` Fix issue detail routing for comments and special IDs
- `889864d` Fix detail popup data and comments route params

## Driftssjekkliste (Azure App Service)

Ved ny deploy, bruk denne korte sjekklisten:

1. Verifiser app settings:
  - `AZURE_STORAGE_CONNECTION_STRING`
  - `AZURE_BLOB_CONTAINER`
  - `SNOWFLAKE_JKS_B64` eller `SNOWFLAKE_JKS_PATH`
  - `SNOWFLAKE_JKS_PASSWORD`
2. Deploy zip med `app.py`, `templates/`, `requirements.txt` og ovrige runtimefiler.
3. Restart appen etter deploy dersom App Service ikke allerede gjør restart.
4. Verifiser helse:
  - applikasjonen svarer pa `/`
  - prosjektliste lastes (Snowflake OK)
  - issue-side viser `Bilder`
  - `Apne bilde` aapner inline i ny fane
5. Ved feil: last ned App Service-logger og se etter importfeil, manglende env-vars eller Snowflake keypair-feil.

## SQL Source

The query in `fetch_photos.py` reads from:

`ISSUES.BIM360CLASSIC_PERSISTANT_STAGE.VW_ISSUES_ENRICHED` joined with `ISSUES.BIM360CLASSIC_PERSISTANT_STAGE.BIM360_ATTACHMENTS` on `issue_id` + `project_id`.

Project scope is controlled by `SNOWFLAKE_PROJECT_ID`.

## Logging

Logs are written to:

- Standard output
- `fetch_photos.log`

Useful messages:

- `SKIP (exists)` means the blob already exists and was not re-downloaded.
- `FAIL download` usually indicates auth/session or URL access issues.
- `FAIL upload` usually indicates Azure permissions or connectivity issues.

## Troubleshooting

- If a public attachment URL fails, verify the `original_url` value in Snowflake is still reachable from your network.
- If Snowflake login fails, verify your SSO access and Snowflake role/warehouse values.
- If Azure upload fails, verify `AZURE_STORAGE_CONNECTION_STRING` and container-level permissions.

## Notes

- Uploads use `overwrite=True`, but existing blobs are checked first and normally skipped.
- Blob content type is inferred from file extension; unknown types fall back to `application/octet-stream`.
