from __future__ import annotations

import base64
import json
import mimetypes
import os
import threading
import importlib
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import snowflake.connector
from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, load_der_private_key
from dotenv import load_dotenv
from flask import Flask, Response, abort, redirect, render_template, request, session, url_for

load_dotenv()

_APP_ROOT = Path(__file__).resolve().parent


def _resolve_template_dir() -> Path:
    candidates = (
        _APP_ROOT / "templates",
        Path.cwd() / "templates",
        Path("/home/site/wwwroot/templates"),
    )
    for candidate in candidates:
        if candidate.exists() and (candidate / "index.html").exists() and (candidate / "base.html").exists():
            return candidate
    return _APP_ROOT / "templates"


_TEMPLATE_DIR = _resolve_template_dir()

app = Flask(__name__, template_folder=str(_TEMPLATE_DIR))
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "clasicfieldphoto-dev-secret")
app.permanent_session_lifetime = timedelta(hours=12)


def _ensure_runtime_templates() -> None:
    _TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

    templates = {
        "base.html": '''<!doctype html>
<html lang="no">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{{ title or "BIM360 Issues" }}</title>
    <style>
        :root {
            --bg: #f6f7f4;
            --paper: #ffffff;
            --ink: #1f2a2b;
            --muted: #5a6a6a;
            --accent: #0e7a6d;
            --line: #dce3dd;
            --chip: #eef5f3;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
            color: var(--ink);
            background:
                radial-gradient(1200px 300px at 10% -5%, #dcefe9 0%, transparent 70%),
                radial-gradient(900px 250px at 100% 0%, #e9ede3 0%, transparent 65%),
                var(--bg);
        }
        .wrap {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        .top {
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 14px;
            padding: 16px 18px;
            margin-bottom: 16px;
        }
        .topbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            margin-bottom: 10px;
        }
        .logout-link {
            color: #0a5f88;
            font-size: 14px;
            font-weight: 600;
        }
        h1, h2, h3 { margin: 0 0 10px; }
        .sub { color: var(--muted); margin: 0; }
        .card {
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 14px;
            padding: 16px;
            margin-bottom: 12px;
        }
        .row {
            display: grid;
            grid-template-columns: minmax(300px, 1.3fr) 1fr 160px 210px 220px;
            gap: 10px;
            align-items: center;
        }
        input, select, button {
            border: 1px solid #becac5;
            border-radius: 10px;
            padding: 10px 12px;
            font: inherit;
        }
        button {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
            cursor: pointer;
        }
        button:hover { filter: brightness(0.95); }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        th, td {
            text-align: left;
            vertical-align: top;
            border-bottom: 1px solid var(--line);
            padding: 10px 8px;
        }
        .chip {
            display: inline-block;
            background: var(--chip);
            color: #1d4f47;
            border: 1px solid #cce0d8;
            border-radius: 999px;
            padding: 2px 8px;
            font-size: 12px;
        }
        a { color: #0a5f88; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
            gap: 12px;
        }
        .split-layout {
            display: grid;
            grid-template-columns: minmax(0, 1.3fr) minmax(320px, 1fr);
            gap: 14px;
            align-items: start;
        }
        .split-panel {
            border-left: 1px solid var(--line);
            padding-left: 14px;
        }
        .photo {
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 10px;
        }
        .photo img {
            width: 100%;
            height: 180px;
            object-fit: cover;
            border-radius: 8px;
            background: #eef2ef;
            border: 1px solid #d9e2dc;
        }
        .kvs {
            display: grid;
            grid-template-columns: 170px 1fr;
            gap: 8px 14px;
            font-size: 14px;
        }
        .kvs .k { color: var(--muted); }
        @media (max-width: 900px) {
            .row { grid-template-columns: 1fr; }
            .kvs { grid-template-columns: 1fr; }
            .split-layout { grid-template-columns: 1fr; }
            .split-panel {
                border-left: none;
                border-top: 1px solid var(--line);
                padding-left: 0;
                padding-top: 12px;
            }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <header class="top">
            <div class="topbar">
                <h1>Bim360 Classicfield Arkiv</h1>
                <div>
                    {% if session.get("is_authenticated") %}
                        <span class="sub">Innlogget som {{ session.get("user_name") }}</span>
                        &nbsp;|&nbsp;
                        <a class="logout-link" href="/logout">Logg ut</a>
                    {% endif %}
                </div>
            </div>
            <p class="sub">Velg prosjekt, søk i issues, og drill ned til vedlegg/bilder.</p>
        </header>
        {% block content %}{% endblock %}
    </div>
</body>
</html>
''',
                "login.html": '''{% extends "base.html" %}

{% block content %}
<section class="card" style="max-width: 480px; margin: 0 auto;">
    <h2>Logg inn</h2>
    <p class="sub">Du må logge inn for å bruke appen.</p>

    {% if error %}
        <p style="color:#b91c1c;background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:10px 12px;">{{ error }}</p>
    {% endif %}

    <form method="post" action="/login">
        <input type="hidden" name="next" value="{{ next }}" />
        <div style="display:grid;gap:10px;">
            <input type="text" name="username" placeholder="Brukernavn" autocomplete="username" required />
            <input type="password" name="password" placeholder="Passord" autocomplete="current-password" required />
            <button type="submit">Logg inn</button>
        </div>
    </form>
</section>
{% endblock %}
''',
                "index.html": '''{% extends "base.html" %}

{% block content %}
<section class="card">
    <form method="get" action="/">
        <div class="row">
            <input
                type="text"
                name="project_pick"
                list="project-options"
                value="{{ project_pick_display }}"
                placeholder="Velg eller søk prosjekt (navn eller id)"
            />
            <datalist id="project-options">
                {% for p in projects %}
                    <option value="{{ (p.PROJECT_NAME or '(uten navn)') ~ ' | ' ~ p.PROJECT_ID }}"></option>
                {% endfor %}
            </datalist>
            <input type="hidden" name="project_id" value="{{ project_id }}" />
            <input type="text" name="q" value="{{ search }}" placeholder="Søk i issues (tomt felt = vis alle issues i prosjektet)" {% if not project_id %}disabled{% endif %} />
            <select name="status" {% if not project_id %}disabled{% endif %}>
                <option value="">Alle status</option>
                {% for s in statuses %}
                    <option value="{{ s }}" {% if s == status %}selected{% endif %}>{{ s }}</option>
                {% endfor %}
            </select>
            <select name="root_cause" {% if not project_id %}disabled{% endif %}>
                <option value="">Alle root causes</option>
                {% for rc in root_causes %}
                    <option value="{{ rc }}" {% if rc == root_cause %}selected{% endif %}>{{ rc }}</option>
                {% endfor %}
            </select>
            <select name="company" {% if not project_id %}disabled{% endif %}>
                <option value="">Alle selskaper</option>
                {% for c in companies %}
                    <option value="{{ c }}" {% if c == company %}selected{% endif %}>{{ c }}</option>
                {% endfor %}
            </select>
        </div>
    </form>
</section>

{% if db_error %}
<section class="card" style="border-color:#e11d48;background:#fff1f2;color:#881337;">
    {{ db_error }}
</section>
{% endif %}

<script>
    (function () {
        const form = document.querySelector('form[action="/"]');
        if (!form) return;

        const projectInput = form.querySelector('input[name="project_pick"]');
        const projectIdHidden = form.querySelector('input[name="project_id"]');
        const searchInput = form.querySelector('input[name="q"]');
        const statusSelect = form.querySelector('select[name="status"]');
        const rootCauseSelect = form.querySelector('select[name="root_cause"]');
        const companySelect = form.querySelector('select[name="company"]');
        if (!projectInput || !projectIdHidden) return;

        const optionSet = new Set(
            Array.from(document.querySelectorAll('#project-options option'))
                .map((o) => (o.value || '').trim())
                .filter(Boolean)
        );

        const extractProjectId = (value) => {
            const raw = (value || '').trim();
            if (!raw) return '';
            if (raw.includes('|')) return raw.split('|').pop().trim();
            return raw;
        };

        const syncProjectIdFromInput = () => {
            const picked = (projectInput.value || '').trim();
            if (!picked) {
                projectIdHidden.value = '';
                return '';
            }

            if (optionSet.has(picked) || picked.includes('|')) {
                const resolved = extractProjectId(picked);
                projectIdHidden.value = resolved;
                return resolved;
            }

            return (projectIdHidden.value || '').trim();
        };

        const setFilterState = (enabled) => {
            if (searchInput) searchInput.disabled = !enabled;
            if (statusSelect) statusSelect.disabled = !enabled;
            if (rootCauseSelect) rootCauseSelect.disabled = !enabled;
            if (companySelect) companySelect.disabled = !enabled;
        };

        let timer = null;
        projectInput.addEventListener('input', function () {
            if (timer) clearTimeout(timer);
            timer = setTimeout(function () {
                const picked = (projectInput.value || '').trim();
                if (!picked || !optionSet.has(picked)) {
                    setFilterState(false);
                    return;
                }

                const previousId = (projectIdHidden.value || '').trim();
                const nextId = syncProjectIdFromInput();
                if (!nextId || nextId === previousId) return;

                setFilterState(true);
                form.requestSubmit();
            }, 100);
        });

        form.addEventListener('submit', function (event) {
            const projectId = syncProjectIdFromInput();
            const hasProject = !!projectId;
            setFilterState(hasProject);
            if (!hasProject) {
                event.preventDefault();
                projectInput.focus();
            }
        });

        if (statusSelect) {
            statusSelect.addEventListener('change', function () {
                const projectId = syncProjectIdFromInput();
                if (!projectId) return;
                setFilterState(true);
                form.requestSubmit();
            });
        }

        if (rootCauseSelect) {
            rootCauseSelect.addEventListener('change', function () {
                const projectId = syncProjectIdFromInput();
                if (!projectId) return;
                setFilterState(true);
                form.requestSubmit();
            });
        }

        if (companySelect) {
            companySelect.addEventListener('change', function () {
                const projectId = syncProjectIdFromInput();
                if (!projectId) return;
                setFilterState(true);
                form.requestSubmit();
            });
        }

        if (searchInput) {
            searchInput.addEventListener('blur', function () {
                const projectId = syncProjectIdFromInput();
                if (!projectId) return;
                setFilterState(true);
                form.requestSubmit();
            });

            searchInput.addEventListener('keydown', function (event) {
                if (event.key !== 'Enter') return;
                event.preventDefault();
                const projectId = syncProjectIdFromInput();
                if (!projectId) return;
                setFilterState(true);
                form.requestSubmit();
            });
        }

        setFilterState(!!(projectIdHidden.value || '').trim());
    })();
</script>

{% if project_id %}
<section class="card split-layout">
    <div>
    <h2>
        {{ selected_project.PROJECT_NAME if selected_project else "Prosjekt" }}
        <span class="chip">{{ total_rows }} treff</span>
    </h2>
    {% if project_summary %}
        <p>
            <span class="chip">Issues: {{ project_summary.issue_count }}</span>
            <span class="chip">Vedlegg/bilder: {{ project_summary.attachment_count }}</span>
            <span class="chip">Side {{ page }} av {{ total_pages }}</span>
        </p>
    {% endif %}

    {% if issues %}
        <table>
            <thead>
                <tr>
                    <th>Issue</th>
                    <th>Status</th>
                    <th>Selskap</th>
                    <th>Issue type</th>
                    <th>Vedlegg</th>
                    <th>Oppdatert</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>
                {% for i in issues %}
                    <tr>
                        <td>
                            <div><strong>{{ i.ISSUE_ID }}</strong></div>
                            <div>{{ i.ISSUE_DESCRIPTION or "-" }}</div>
                        </td>
                        <td>{{ i.STATUS or "-" }}</td>
                        <td>{{ i.COMPANY_NAME or "-" }}</td>
                        <td>{{ i.ISSUE_TYPE_NAME or "-" }}</td>
                        <td>{{ i.ATTACHMENT_COUNT }}</td>
                        <td>{{ i.UPDATED_AT or "-" }}</td>
                        <td>
                            <a href="/?project_pick={{ project_pick_display }}&project_id={{ project_id }}&q={{ search }}&status={{ status }}&root_cause={{ root_cause }}&company={{ company }}&page={{ page }}&issue_id={{ i.ISSUE_ID }}">Bilder</a>
                        </td>
                    </tr>
                {% endfor %}
            </tbody>
        </table>

        <p>
            {% if page > 1 %}
                <a href="/?project_pick={{ project_pick_display }}&project_id={{ project_id }}&q={{ search }}&status={{ status }}&root_cause={{ root_cause }}&company={{ company }}&page={{ page - 1 }}&issue_id={{ split_issue_id }}">Forrige</a>
            {% endif %}
            {% if page > 1 and page < total_pages %} | {% endif %}
            {% if page < total_pages %}
                <a href="/?project_pick={{ project_pick_display }}&project_id={{ project_id }}&q={{ search }}&status={{ status }}&root_cause={{ root_cause }}&company={{ company }}&page={{ page + 1 }}&issue_id={{ split_issue_id }}">Neste</a>
            {% endif %}
        </p>
    {% else %}
        <p>Ingen issues funnet for valgte filter.</p>
    {% endif %}
    </div>

    <aside class="split-panel">
        {% if split_issue %}
            <h3>Bilder for issue {{ split_issue.ISSUE_ID }}</h3>
            <p>{{ split_issue.ISSUE_DESCRIPTION or "Ingen beskrivelse" }}</p>

            {% if split_attachments %}
                <div class="grid">
                    {% for a in split_attachments %}
                    <article class="photo">
                        {% if a.IS_IMAGE and a.PREVIEW_URL %}
                            <img src="{{ a.PREVIEW_URL }}" alt="{{ a.FILE_NAME }}" loading="lazy" />
                        {% else %}
                            <img alt="Ingen forhåndsvisning" loading="lazy" />
                        {% endif %}
                        <p><strong>{{ a.FILE_NAME or "attachment" }}</strong></p>
                        {% if a.OPEN_URL %}
                            <p><a href="{{ a.OPEN_URL }}" target="_blank" rel="noopener">Åpne bilde</a></p>
                        {% endif %}
                    </article>
                    {% endfor %}
                </div>
            {% else %}
                <p>Ingen vedlegg funnet på denne issue.</p>
            {% endif %}
        {% else %}
            <h3>Bilder</h3>
            <p>Velg Bilder på en issue i tabellen for å vise bilder i splittet visning.</p>
        {% endif %}
    </aside>
</section>
{% endif %}
{% endblock %}
''',
                "issue.html": '''{% extends "base.html" %}

{% block content %}
<section class="card">
    <h2>Issue {{ issue.ISSUE_ID }}</h2>
    <p>{{ issue.ISSUE_DESCRIPTION or "Ingen beskrivelse" }}</p>
    <div class="kvs">
        <div class="k">Prosjekt</div><div>{{ issue.PROJECT_NAME or issue.PROJECT_ID }}</div>
        <div class="k">Status</div><div>{{ issue.STATUS or "-" }}</div>
        <div class="k">Selskap</div><div>{{ issue.COMPANY_NAME or "-" }}</div>
        <div class="k">Issue type</div><div>{{ issue.ISSUE_TYPE_FULL_NAME or issue.ISSUE_TYPE_NAME or "-" }}</div>
        <div class="k">Root cause</div><div>{{ issue.ROOT_CAUSE_FULL_NAME or issue.ROOT_CAUSE_NAME or "-" }}</div>
        <div class="k">Opprettet</div><div>{{ issue.CREATED_AT or "-" }}</div>
        <div class="k">Oppdatert</div><div>{{ issue.UPDATED_AT or "-" }}</div>
        <div class="k">Lukket</div><div>{{ issue.CLOSED_AT or "-" }}</div>
    </div>
</section>

<section class="card">
    <h3>Vedlegg og bilder <span class="chip">{{ attachments|length }}</span></h3>
    {% if attachments %}
        <div class="grid">
            {% for a in attachments %}
            <article class="photo">
                {% if a.IS_IMAGE and a.PREVIEW_URL %}
                    <img src="{{ a.PREVIEW_URL }}" alt="{{ a.FILE_NAME }}" loading="lazy" />
                {% else %}
                    <img alt="Ingen forhåndsvisning" loading="lazy" />
                {% endif %}
                <p><strong>{{ a.FILE_NAME or "attachment" }}</strong></p>
                {% if a.OPEN_URL %}
                    <p><a href="{{ a.OPEN_URL }}" target="_blank" rel="noopener">Åpne bilde</a></p>
                {% endif %}
                {% if a.SOURCE_URL %}
                    <p><a href="{{ a.SOURCE_URL }}" target="_blank" rel="noopener">Kilde-URL</a></p>
                {% endif %}
            </article>
            {% endfor %}
        </div>
    {% else %}
        <p>Ingen vedlegg registrert på denne issue.</p>
    {% endif %}
</section>

<section>
    <a href="/?project_id={{ issue.PROJECT_ID }}">Tilbake til prosjekt</a>
</section>
{% endblock %}
''',
        }

    required_templates = set(templates.keys())
    existing_templates = {p.name for p in _TEMPLATE_DIR.glob("*.html")}
    if required_templates.issubset(existing_templates):
        return

    for template_name, template_content in templates.items():
        template_path = _TEMPLATE_DIR / template_name
        if not template_path.exists():
            template_path.write_text(template_content, encoding="utf-8")


_ensure_runtime_templates()

# Snowflake configuration
SNOWFLAKE_ACCOUNT = os.environ.get("SNOWFLAKE_ACCOUNT", "PGODCHG-UR78062")
SNOWFLAKE_USER = os.environ.get("SNOWFLAKE_USER", "NOSYS_ISSUES_KEYPAIR")
SNOWFLAKE_ROLE = os.environ.get("SNOWFLAKE_ROLE", "NOSYS_ISSUES")
SNOWFLAKE_WAREHOUSE = os.environ.get("SNOWFLAKE_WAREHOUSE", "INTEGRATION_WH")
SNOWFLAKE_DATABASE = os.environ.get("SNOWFLAKE_DATABASE", "ISSUES")
SNOWFLAKE_SCHEMA = os.environ.get("SNOWFLAKE_SCHEMA", "BIM360CLASSIC_PERSISTANT_STAGE")
SNOWFLAKE_JKS_PATH = os.environ.get("SNOWFLAKE_JKS_PATH", "snowflake1(1).jks")
SNOWFLAKE_JKS_B64 = os.environ.get("SNOWFLAKE_JKS_B64", "")
SNOWFLAKE_JKS_ALIAS = os.environ.get("SNOWFLAKE_JKS_ALIAS", "snowflake")
SNOWFLAKE_JKS_PASSWORD = os.environ.get("SNOWFLAKE_JKS_PASSWORD", "")
SNOWFLAKE_JKS_KEY_PASSWORD = os.environ.get("SNOWFLAKE_JKS_KEY_PASSWORD", "")
SNOWFLAKE_AZURE_SAS_TOKEN = os.environ.get("SNOWFLAKE_AZURE_SAS_TOKEN", "")

# Azure Blob configuration
AZURE_CONN_STR = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
AZURE_CONTAINER = os.environ.get("AZURE_BLOB_CONTAINER", "clasicfieldphoto")
AZURE_SAS_HOURS = int(os.environ.get("AZURE_SAS_HOURS", "12"))

ISSUES_VIEW = f"{SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}.VW_ISSUES_ENRICHED"
ATTACHMENTS_TABLE = f"{SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}.BIM360_ATTACHMENTS"
PAGE_SIZE = int(os.environ.get("WEB_PAGE_SIZE", "50"))

_SF_CONN = None
_SF_CONN_LOCK = threading.Lock()
_BLOB_SERVICE_CLIENT = None
_BLOB_SERVICE_CLIENT_LOCK = threading.Lock()


def _load_private_key_der_from_keytool(jks_path: Path) -> bytes:
    key_password = SNOWFLAKE_JKS_KEY_PASSWORD
    if not key_password:
        raise RuntimeError(
            "Missing SNOWFLAKE_JKS_KEY_PASSWORD. The private key password is required when using keytool fallback."
        )

    p12_password = f"tmp-{uuid.uuid4()}"
    p12_path = Path(tempfile.gettempdir()) / f"snowflake_{uuid.uuid4().hex}.p12"

    cmd = [
        "keytool",
        "-importkeystore",
        "-noprompt",
        "-srckeystore",
        str(jks_path),
        "-srcstoretype",
        "JKS",
        "-srcstorepass",
        SNOWFLAKE_JKS_PASSWORD,
        "-srcalias",
        SNOWFLAKE_JKS_ALIAS,
        "-srckeypass",
        key_password,
        "-destkeystore",
        str(p12_path),
        "-deststoretype",
        "PKCS12",
        "-deststorepass",
        p12_password,
        "-destkeypass",
        p12_password,
        "-destalias",
        SNOWFLAKE_JKS_ALIAS,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "keytool failed").strip()
        raise RuntimeError(f"Unable to convert JKS key with keytool: {detail}")

    try:
        with p12_path.open("rb") as f:
            p12_data = f.read()
    finally:
        try:
            p12_path.unlink(missing_ok=True)
        except Exception:
            pass

    from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

    private_key, _cert, _extra = load_key_and_certificates(p12_data, p12_password.encode())
    if private_key is None:
        raise RuntimeError("No private key extracted from JKS keystore.")

    return private_key.private_bytes(
        encoding=Encoding.DER,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )


def _materialize_jks_file() -> tuple[Path, bool]:
    if SNOWFLAKE_JKS_B64.strip():
        temp_path = Path(tempfile.gettempdir()) / f"snowflake_{uuid.uuid4().hex}.jks"
        temp_path.write_bytes(base64.b64decode(SNOWFLAKE_JKS_B64))
        return temp_path, True

    jks_path = Path(SNOWFLAKE_JKS_PATH)
    if not jks_path.is_absolute():
        jks_path = Path.cwd() / jks_path
    return jks_path, False


def _load_private_key_der_from_jks() -> bytes:
    if not SNOWFLAKE_JKS_PASSWORD:
        raise RuntimeError("Missing SNOWFLAKE_JKS_PASSWORD for keypair authentication.")

    jks_path, created_temp_file = _materialize_jks_file()
    if not jks_path.exists():
        raise FileNotFoundError(f"JKS file not found: {jks_path}")

    try:
        jks = importlib.import_module("jks")
    except ImportError:
        # Local fallback when pyjks is unavailable (e.g., missing build tools).
        return _load_private_key_der_from_keytool(jks_path)

    ks = jks.KeyStore.load(str(jks_path), SNOWFLAKE_JKS_PASSWORD)
    key_entry = ks.private_keys.get(SNOWFLAKE_JKS_ALIAS)
    if key_entry is None:
        aliases = ", ".join(sorted(ks.private_keys.keys())) or "(none)"
        raise KeyError(
            f"JKS alias '{SNOWFLAKE_JKS_ALIAS}' not found. Available private key aliases: {aliases}"
        )

    if not key_entry.is_decrypted():
        key_entry.decrypt(SNOWFLAKE_JKS_KEY_PASSWORD or SNOWFLAKE_JKS_PASSWORD)

    private_key = load_der_private_key(key_entry.pkey_pkcs8, password=None)
    try:
        return private_key.private_bytes(
            encoding=Encoding.DER,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )
    finally:
        if created_temp_file:
            try:
                jks_path.unlink(missing_ok=True)
            except Exception:
                pass


@app.route("/login", methods=["GET", "POST"])
def login():
    return redirect(url_for("index"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.get("/attachment/<project_id>/<issue_id>/<path:file_name>")
def attachment_content(project_id: str, issue_id: str, file_name: str):
    safe_name = PurePosixPath(file_name).name or "attachment"
    try:
        blob_bytes, content_type = download_blob_content(project_id, issue_id, safe_name)
    except Exception:
        app.logger.exception("Failed to load attachment from Azure Blob")
        abort(404)

    response = Response(blob_bytes, mimetype=content_type)
    response.headers["Content-Disposition"] = f'inline; filename="{safe_name}"'
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


def _new_snowflake_conn():
    private_key_der = _load_private_key_der_from_jks()

    conn_kwargs = {
        "account": SNOWFLAKE_ACCOUNT,
        "user": SNOWFLAKE_USER,
        "role": SNOWFLAKE_ROLE,
        "warehouse": SNOWFLAKE_WAREHOUSE,
        "database": SNOWFLAKE_DATABASE,
        "schema": SNOWFLAKE_SCHEMA,
        "client_session_keep_alive": True,
        "private_key": private_key_der,
    }

    if SNOWFLAKE_AZURE_SAS_TOKEN:
        conn_kwargs["credentials"] = {"azure_sas_token": SNOWFLAKE_AZURE_SAS_TOKEN}

    return snowflake.connector.connect(**conn_kwargs)


def _is_conn_alive(conn) -> bool:
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1")
            return True
        finally:
            cur.close()
    except Exception:
        return False


def snowflake_conn():
    global _SF_CONN
    with _SF_CONN_LOCK:
        if _SF_CONN is None or not _is_conn_alive(_SF_CONN):
            if _SF_CONN is not None:
                try:
                    _SF_CONN.close()
                except Exception:
                    pass
            _SF_CONN = _new_snowflake_conn()
        return _SF_CONN


def blob_path(project_id: str, issue_id: str, file_name: str) -> str:
    safe_name = PurePosixPath(file_name).name or "attachment"
    return f"{project_id}/{issue_id}/{safe_name}"


def blob_service_client() -> BlobServiceClient:
    global _BLOB_SERVICE_CLIENT
    if not AZURE_CONN_STR:
        raise RuntimeError("Missing AZURE_STORAGE_CONNECTION_STRING.")

    with _BLOB_SERVICE_CLIENT_LOCK:
        if _BLOB_SERVICE_CLIENT is None:
            _BLOB_SERVICE_CLIENT = BlobServiceClient.from_connection_string(AZURE_CONN_STR)
        return _BLOB_SERVICE_CLIENT


def download_blob_content(project_id: str, issue_id: str, file_name: str) -> tuple[bytes, str]:
    blob_client = blob_service_client().get_blob_client(
        container=AZURE_CONTAINER,
        blob=blob_path(project_id, issue_id, file_name),
    )
    blob_props = blob_client.get_blob_properties()
    content_type = blob_props.content_settings.content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    blob_bytes = blob_client.download_blob().readall()
    return blob_bytes, content_type


def _conn_str_value(key: str) -> str | None:
    for part in AZURE_CONN_STR.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k.strip().lower() == key.lower():
            return v.strip()
    return None


def generate_blob_read_url(project_id: str, issue_id: str, file_name: str) -> str | None:
    if not AZURE_CONN_STR:
        return None

    account_name = _conn_str_value("AccountName")
    account_key = _conn_str_value("AccountKey")
    endpoint_suffix = _conn_str_value("EndpointSuffix") or "core.windows.net"
    protocol = _conn_str_value("DefaultEndpointsProtocol") or "https"

    if not account_name or not account_key:
        return None

    blob_name = blob_path(project_id, issue_id, file_name)
    content_type, _ = mimetypes.guess_type(file_name)
    response_content_type = content_type or "application/octet-stream"
    response_content_disposition = f'inline; filename="{PurePosixPath(file_name).name or "attachment"}"'
    sas = generate_blob_sas(
        account_name=account_name,
        container_name=AZURE_CONTAINER,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=AZURE_SAS_HOURS),
        content_type=response_content_type,
        content_disposition=response_content_disposition,
    )
    blob_url = f"{protocol}://{account_name}.blob.{endpoint_suffix}/{AZURE_CONTAINER}/{quote(blob_name)}"
    return f"{blob_url}?{sas}"


def is_image_name(file_name: str) -> bool:
    ctype, _ = mimetypes.guess_type(file_name)
    return bool(ctype and ctype.startswith("image/"))


def _preferred_attachment_url(azure_blob_url: str | None, source_url: str | None) -> str | None:
    return azure_blob_url or source_url or None


def format_issue_field(value: Any, empty_text: str) -> str:
    if value is None:
        return empty_text
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, ensure_ascii=False)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return empty_text
        try:
            parsed = json.loads(stripped)
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception:
            return stripped
    return str(value)


def _parse_json_like(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except Exception:
            return None
    return None


def _extract_comment_text(item: dict[str, Any]) -> str:
    text_keys = (
        "comment",
        "message",
        "body",
        "text",
        "content",
        "description",
        "value",
    )
    for key in text_keys:
        value = get_row_value(item, key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, dict):
            nested = get_row_value(value, "text", "value", "message")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return ""


def _extract_comment_author(item: dict[str, Any]) -> str:
    author_keys = (
        "author_name",
        "author",
        "created_by_name",
        "created_by",
        "createdBy",
        "user_name",
        "user",
        "owner",
        "display_name",
        "name",
    )
    for key in author_keys:
        value = get_row_value(item, key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = get_row_value(value, "name", "display_name", "displayName", "full_name", "email", "id")
            if nested is not None:
                nested_text = str(nested).strip()
                if nested_text:
                    return nested_text
    return "Ukjent"


def _extract_comment_time(item: dict[str, Any]) -> str:
    time_keys = (
        "created_at",
        "createdAt",
        "timestamp",
        "time",
        "date",
        "posted_at",
        "updated_at",
    )
    for key in time_keys:
        value = get_row_value(item, key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def parse_issue_comments(value: Any) -> list[dict[str, str]]:
    parsed = _parse_json_like(value)
    rows: list[Any] = []

    if isinstance(parsed, list):
        rows = parsed
    elif isinstance(parsed, dict):
        for key in ("comments", "items", "entries", "data", "results"):
            nested = get_row_value(parsed, key)
            if isinstance(nested, list):
                rows = nested
                break
        if not rows:
            rows = [parsed]
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return [{"author": "Kommentar", "time": "", "text": stripped}]
        return []
    elif value is not None:
        return [{"author": "Kommentar", "time": "", "text": str(value)}]

    comments: list[dict[str, str]] = []
    for row in rows:
        if isinstance(row, dict):
            text = _extract_comment_text(row)
            if not text:
                text = json.dumps(row, ensure_ascii=False)
            comments.append(
                {
                    "author": _extract_comment_author(row),
                    "time": _extract_comment_time(row),
                    "text": text,
                }
            )
            continue

        text = str(row).strip()
        if text:
            comments.append({"author": "Kommentar", "time": "", "text": text})

    return comments


def get_row_value(row: dict[str, Any] | None, *names: str) -> Any:
    if not row:
        return None

    for name in names:
        if name in row:
            return row.get(name)

    lowered = {str(key).lower(): key for key in row.keys()}
    for name in names:
        match_key = lowered.get(name.lower())
        if match_key is not None:
            return row.get(match_key)

    return None


def normalize_row_keys(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None

    normalized: dict[str, Any] = {}
    for key, value in row.items():
        normalized[key] = value
        normalized[str(key).upper()] = value
        normalized[str(key).lower()] = value
    return normalized


def query_projects() -> list[dict[str, Any]]:
    sql = f"""
    SELECT DISTINCT "project_id" AS project_id, "project_name" AS project_name
    FROM {ISSUES_VIEW}
    WHERE "project_id" IS NOT NULL
    ORDER BY "project_name" NULLS LAST, "project_id"
    """
    con = snowflake_conn()
    cur = con.cursor(snowflake.connector.DictCursor)
    try:
        cur.execute(sql)
        return cur.fetchall()
    finally:
        cur.close()


def resolve_project_id(project_pick: str, projects: list[dict[str, Any]]) -> str:
    """Resolve user-entered project text to a concrete project_id.

    Accepts formats like:
    - exact project id
    - exact project name
    - "<project_name> | <project_id>"
    """
    if not project_pick:
        return ""

    raw = project_pick.strip()
    if not raw:
        return ""

    if "|" in raw:
        maybe_id = raw.split("|")[-1].strip()
        for p in projects:
            if (p.get("PROJECT_ID") or "") == maybe_id:
                return maybe_id

    for p in projects:
        if (p.get("PROJECT_ID") or "") == raw:
            return raw

    for p in projects:
        if (p.get("PROJECT_NAME") or "") == raw:
            return p.get("PROJECT_ID") or ""

    return ""


def query_project_summary(project_id: str) -> dict[str, int]:
    sql = f"""
    WITH issue_cte AS (
        SELECT COUNT(*) AS issue_count
        FROM {ISSUES_VIEW}
        WHERE "project_id" = %s
    ),
    attachment_cte AS (
        SELECT COUNT(*) AS attachment_count
        FROM {ATTACHMENTS_TABLE}
        WHERE project_id = %s
    )
    SELECT issue_count, attachment_count
    FROM issue_cte, attachment_cte
    """
    con = snowflake_conn()
    cur = con.cursor(snowflake.connector.DictCursor)
    try:
        cur.execute(sql, (project_id, project_id))
        row = cur.fetchone() or {}
        return {
            "issue_count": int(row.get("ISSUE_COUNT") or 0),
            "attachment_count": int(row.get("ATTACHMENT_COUNT") or 0),
        }
    finally:
        cur.close()


def query_statuses(project_id: str) -> list[str]:
    sql = f"""
        SELECT DISTINCT "status" AS status
    FROM {ISSUES_VIEW}
        WHERE "project_id" = %s
            AND "status" IS NOT NULL
        ORDER BY "status"
    """
    con = snowflake_conn()
    cur = con.cursor()
    try:
        cur.execute(sql, (project_id,))
        return [str(row[0]) for row in cur.fetchall()]
    finally:
        cur.close()


def query_root_causes(project_id: str) -> list[str]:
    sql = f"""
        SELECT DISTINCT "root_cause_name" AS root_cause_name
    FROM {ISSUES_VIEW}
        WHERE "project_id" = %s
            AND "root_cause_name" IS NOT NULL
        ORDER BY "root_cause_name"
    """
    con = snowflake_conn()
    cur = con.cursor()
    try:
        cur.execute(sql, (project_id,))
        return [str(row[0]) for row in cur.fetchall()]
    finally:
        cur.close()


def query_companies(project_id: str) -> list[str]:
    sql = f"""
        SELECT DISTINCT "company_name" AS company_name
    FROM {ISSUES_VIEW}
        WHERE "project_id" = %s
            AND "company_name" IS NOT NULL
        ORDER BY "company_name"
    """
    con = snowflake_conn()
    cur = con.cursor()
    try:
        cur.execute(sql, (project_id,))
        return [str(row[0]) for row in cur.fetchall()]
    finally:
        cur.close()


def query_issue_types(project_id: str) -> list[str]:
    sql = f"""
        SELECT DISTINCT "issue_type_name" AS issue_type_name
    FROM {ISSUES_VIEW}
        WHERE "project_id" = %s
            AND "issue_type_name" IS NOT NULL
        ORDER BY "issue_type_name"
    """
    con = snowflake_conn()
    cur = con.cursor()
    try:
        cur.execute(sql, (project_id,))
        return [str(row[0]) for row in cur.fetchall()]
    finally:
        cur.close()


def query_locations(project_id: str) -> list[str]:
    sql = f"""
        SELECT DISTINCT "location_path" AS location_path
    FROM {ISSUES_VIEW}
        WHERE "project_id" = %s
            AND "location_path" IS NOT NULL
        ORDER BY "location_path"
    """
    con = snowflake_conn()
    cur = con.cursor()
    try:
        cur.execute(sql, (project_id,))
        return [str(row[0]) for row in cur.fetchall()]
    finally:
        cur.close()


def query_issues(
    project_id: str,
    search: str,
    status: str,
    root_cause: str,
    company: str,
    issue_type: str,
    location_path: str,
    page: int,
) -> tuple[list[dict[str, Any]], int]:
    search_like = f"%{search}%"
    status_filter = status.strip().lower()
    root_cause_filter = root_cause.strip().lower()
    company_filter = company.strip().lower()
    issue_type_filter = issue_type.strip().lower()
    location_path_filter = location_path.strip().lower()
    offset = (page - 1) * PAGE_SIZE

    where_sql = """
        v."project_id" = %s
      AND (
        %s = ''
                OR v."issue_id" ILIKE %s
                OR v."issue_description" ILIKE %s
                OR v."company_name" ILIKE %s
                OR v."issue_type_name" ILIKE %s
      )
      AND (
        %s = ''
                OR LOWER(v."status") = %s
      )
            AND (
                %s = ''
                                OR LOWER(v."root_cause_name") = %s
            )
            AND (
                %s = ''
                                OR LOWER(v."company_name") = %s
            )
            AND (
                %s = ''
                                OR LOWER(v."issue_type_name") = %s
            )
            AND (
                %s = ''
                                OR LOWER(v."location_path") = %s
            )
    """

    count_sql = f"""
    SELECT COUNT(*) AS total_rows
    FROM {ISSUES_VIEW} v
    WHERE {where_sql}
    """

    sql = f"""
    WITH attachment_counts AS (
        SELECT project_id, issue_id, COUNT(*) AS attachment_count
        FROM {ATTACHMENTS_TABLE}
        WHERE project_id = %s
        GROUP BY project_id, issue_id
    )
    SELECT
        v."project_id" AS project_id,
        v."issue_id" AS issue_id,
        v."issue_description" AS issue_description,
        v."status" AS status,
        v."root_cause_name" AS root_cause_name,
        v."company_name" AS company_name,
        v."issue_type_name" AS issue_type_name,
        v."location_path" AS location_path,
        v."created_at" AS created_at,
        v."updated_at" AS updated_at,
        v."closed_at" AS closed_at,
        COALESCE(a.attachment_count, 0) AS attachment_count
    FROM {ISSUES_VIEW} v
    LEFT JOIN attachment_counts a
        ON a.project_id = v."project_id"
       AND a.issue_id = v."issue_id"
    WHERE {where_sql}
    ORDER BY v."updated_at" DESC NULLS LAST
    LIMIT %s OFFSET %s
    """

    con = snowflake_conn()
    cur = con.cursor(snowflake.connector.DictCursor)
    try:
        filter_params = (
            project_id,
            search,
            search_like,
            search_like,
            search_like,
            search_like,
            status_filter,
            status_filter,
            root_cause_filter,
            root_cause_filter,
            company_filter,
            company_filter,
            issue_type_filter,
            issue_type_filter,
            location_path_filter,
            location_path_filter,
        )
        cur.execute(count_sql, filter_params)
        count_row = cur.fetchone() or {}
        total_rows = int(count_row.get("TOTAL_ROWS") or count_row.get("total_rows") or 0)

        cur.execute(
            sql,
            (
                project_id,
                *filter_params,
                PAGE_SIZE,
                offset,
            ),
        )
        return cur.fetchall(), total_rows
    finally:
        cur.close()


def query_issue(project_id: str, issue_id: str) -> dict[str, Any] | None:
    sql = f"""
    SELECT *
    FROM {ISSUES_VIEW}
        WHERE "project_id" = %s
            AND "issue_id" = %s
    LIMIT 1
    """
    con = snowflake_conn()
    cur = con.cursor(snowflake.connector.DictCursor)
    try:
        cur.execute(sql, (project_id, issue_id))
        return normalize_row_keys(cur.fetchone())
    finally:
        cur.close()


def query_attachments(project_id: str, issue_id: str) -> list[dict[str, Any]]:
    sql = f"""
    SELECT
                issue_id,
                project_id,
                file_name,
                url_without_ticket,
                blobstore_url
    FROM {ATTACHMENTS_TABLE}
        WHERE project_id = %s
            AND issue_id = %s
        ORDER BY file_name
    """
    con = snowflake_conn()
    cur = con.cursor(snowflake.connector.DictCursor)
    try:
        cur.execute(sql, (project_id, issue_id))
        rows = cur.fetchall()
    finally:
        cur.close()

    for row in rows:
        file_name = row.get("FILE_NAME") or "attachment"
        source_url = row.get("URL_WITHOUT_TICKET") or row.get("BLOBSTORE_URL")
        row["SOURCE_URL"] = source_url
        row["IS_IMAGE"] = is_image_name(file_name)
        row["AZURE_BLOB_URL"] = generate_blob_read_url(project_id, issue_id, file_name)
        proxied_url = None
        if AZURE_CONN_STR and AZURE_CONTAINER:
            proxied_url = url_for(
                "attachment_content",
                project_id=project_id,
                issue_id=issue_id,
                file_name=PurePosixPath(file_name).name or "attachment",
            )
        row["PREVIEW_URL"] = proxied_url or _preferred_attachment_url(row["AZURE_BLOB_URL"], source_url)
        row["OPEN_URL"] = proxied_url or _preferred_attachment_url(row["AZURE_BLOB_URL"], source_url)

    return rows


@app.get("/")
def index():
    project_pick = request.args.get("project_pick", "").strip()
    project_id = request.args.get("project_id", "").strip()
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    root_cause = request.args.get("root_cause", "").strip()
    company = request.args.get("company", "").strip()
    issue_type = request.args.get("issue_type", "").strip()
    location_path = request.args.get("location_path", "").strip()
    split_issue_id = request.args.get("issue_id", "").strip()
    split_view = request.args.get("split_view", "images").strip().lower()
    if split_view not in {"images", "comments", "history"}:
        split_view = "images"
    page = max(1, request.args.get("page", type=int, default=1))
    has_follow_up_filters = bool(
        search
        or status
        or root_cause
        or company
        or issue_type
        or location_path
        or split_issue_id
        or "page" in request.args
    )
    has_explicit_project = bool(project_pick or project_id)

    db_error = None
    try:
        projects = query_projects()
    except Exception:
        app.logger.exception("Failed to load projects from Snowflake")
        projects = []
        db_error = (
            "Kunne ikke koble til Snowflake fra web appen. "
            "Sjekk Snowflake app settings i Azure (authenticator og credentials)."
        )

    resolved_project_id = resolve_project_id(project_pick, projects) if project_pick else ""
    if resolved_project_id:
        project_id = resolved_project_id
    elif not project_id and has_follow_up_filters and not has_explicit_project:
        project_id = (session.get("project_id") or "").strip()

    if project_id:
        session["project_id"] = project_id
    else:
        session.pop("project_id", None)

    issues: list[dict[str, Any]] = []
    selected_project = None
    statuses: list[str] = []
    root_causes: list[str] = []
    companies: list[str] = []
    issue_types: list[str] = []
    locations: list[str] = []
    project_summary = None
    total_rows = 0
    total_pages = 0
    split_issue = None
    split_attachments: list[dict[str, Any]] = []
    split_comments: list[dict[str, str]] = []
    split_history_text = "Ingen history-data."
    project_pick_display = project_pick

    if project_id and not db_error:
        selected_project = next((p for p in projects if p["PROJECT_ID"] == project_id), None)
        if selected_project:
            project_pick_display = f"{selected_project.get('PROJECT_NAME') or '(uten navn)'} | {project_id}"
        elif not project_pick_display:
            project_pick_display = project_id
        statuses = query_statuses(project_id)
        root_causes = query_root_causes(project_id)
        companies = query_companies(project_id)
        issue_types = query_issue_types(project_id)
        locations = query_locations(project_id)
        project_summary = query_project_summary(project_id)
        issues, total_rows = query_issues(project_id, search, status, root_cause, company, issue_type, location_path, page)
        total_pages = max(1, (total_rows + PAGE_SIZE - 1) // PAGE_SIZE)
        if page > total_pages:
            page = total_pages
            issues, total_rows = query_issues(project_id, search, status, root_cause, company, issue_type, location_path, page)

        if split_issue_id:
            split_issue = query_issue(project_id, split_issue_id)
            if split_issue:
                split_attachments = query_attachments(project_id, split_issue_id)
                split_comments = parse_issue_comments(get_row_value(split_issue, "COMMENTS", "comments"))
                split_history_text = format_issue_field(get_row_value(split_issue, "ADDITIONAL_FIELDS", "additional_fields"), "Ingen history-data.")

    return render_template(
        "index.html",
        projects=projects,
        issues=issues,
        project_pick=project_pick,
        project_pick_display=project_pick_display,
        project_id=project_id,
        selected_project=selected_project,
        search=search,
        status=status,
        root_cause=root_cause,
        company=company,
        issue_type=issue_type,
        location_path=location_path,
        split_issue_id=split_issue_id,
        split_view=split_view,
        split_issue=split_issue,
        split_attachments=split_attachments,
        split_comments=split_comments,
        split_history_text=split_history_text,
        statuses=statuses,
        root_causes=root_causes,
        companies=companies,
        issue_types=issue_types,
        locations=locations,
        project_summary=project_summary,
        page=page,
        page_size=PAGE_SIZE,
        total_rows=total_rows,
        total_pages=total_pages,
        db_error=db_error,
    )


def _render_issue_detail(project_id: str, issue_id: str):
    issue = query_issue(project_id, issue_id)
    if not issue:
        abort(404)

    active_view = request.args.get("view", "attachments").strip().lower()
    if active_view not in {"attachments", "comments", "history"}:
        active_view = "attachments"

    comments = parse_issue_comments(get_row_value(issue, "COMMENTS", "comments"))
    history_text = format_issue_field(get_row_value(issue, "ADDITIONAL_FIELDS", "additional_fields"), "Ingen history-data.")

    attachments = query_attachments(project_id, issue_id)
    return render_template(
        "issue.html",
        issue=issue,
        attachments=attachments,
        comments=comments,
        history_text=history_text,
        active_view=active_view,
    )


@app.get("/issue")
def issue_detail_query():
    project_id = request.args.get("project_id", "").strip() or request.args.get("PROJECT_ID", "").strip()
    issue_id = request.args.get("issue_id", "").strip() or request.args.get("ISSUE_ID", "").strip()
    if not project_id or not issue_id:
        abort(404)
    return _render_issue_detail(project_id, issue_id)


@app.get("/issue/<project_id>/<path:issue_id>")
def issue_detail(project_id: str, issue_id: str):
    return _render_issue_detail(project_id, issue_id)


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="127.0.0.1", port=8000, debug=debug_mode, use_reloader=False)
