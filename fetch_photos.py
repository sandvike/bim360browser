"""Fetch BIM360 attachments and store them in Azure Blob Storage.

Overview:
1. Read attachment metadata from Snowflake.
2. Open a real browser and complete BIM360 SSO.
3. Download each attachment with browser-authenticated ``fetch()``.
4. Upload files into Azure Blob Storage.

Storage layout:
- Container: ``AZURE_BLOB_CONTAINER`` (default ``clasicfieldphoto``)
- Blob path: ``<project_id>/<issue_id>/<file_name>``

Authentication model:
- Snowflake: ``externalbrowser`` SSO
- BIM360: interactive browser login
- Azure Blob: connection string from environment variables
"""

import base64
import os
import logging
import mimetypes
import importlib
import subprocess
import tempfile
import uuid
import sys
from urllib.request import Request, urlopen
from pathlib import Path, PurePosixPath

import snowflake.connector
from azure.storage.blob import BlobServiceClient, ContentSettings
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, load_der_private_key
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────
SNOWFLAKE_ACCOUNT   = os.environ.get("SNOWFLAKE_ACCOUNT",   "PGODCHG-UR78062")
SNOWFLAKE_USER      = os.environ.get("SNOWFLAKE_USER",      "NOSYS_ISSUES_KEYPAIR")
SNOWFLAKE_ROLE      = os.environ.get("SNOWFLAKE_ROLE",      "NOSYS_ISSUES")
SNOWFLAKE_WAREHOUSE = os.environ.get("SNOWFLAKE_WAREHOUSE", "INTEGRATION_WH")
SNOWFLAKE_DATABASE  = os.environ.get("SNOWFLAKE_DATABASE",  "ISSUES")
SNOWFLAKE_SCHEMA    = os.environ.get("SNOWFLAKE_SCHEMA",    "BIM360CLASSIC_PERSISTANT_STAGE")
SNOWFLAKE_PROJECT_ID = os.environ.get("SNOWFLAKE_PROJECT_ID", "1c44f9c6-37ff-4499-b24f-0af8ae355161")
SNOWFLAKE_JKS_PATH = os.environ.get("SNOWFLAKE_JKS_PATH", "snowflake1(1).jks")
SNOWFLAKE_JKS_B64 = os.environ.get("SNOWFLAKE_JKS_B64", "")
SNOWFLAKE_JKS_ALIAS = os.environ.get("SNOWFLAKE_JKS_ALIAS", "snowflake")
SNOWFLAKE_JKS_PASSWORD = os.environ.get("SNOWFLAKE_JKS_PASSWORD", "")
SNOWFLAKE_JKS_KEY_PASSWORD = os.environ.get("SNOWFLAKE_JKS_KEY_PASSWORD", "")
SNOWFLAKE_AZURE_SAS_TOKEN = os.environ.get("SNOWFLAKE_AZURE_SAS_TOKEN", "")

AZURE_CONN_STR  = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
AZURE_CONTAINER = os.environ.get("AZURE_BLOB_CONTAINER", "clasicfieldphoto")

SQL = f"""
SELECT
    COALESCE(a.original_url, a.url_without_ticket, a.blobstore_url) AS attachment_url,
    a.file_name,
    v."issue_id" AS issue_id,
    v."project_id" AS project_id
FROM   {SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}.VW_ISSUES_ENRICHED v
JOIN   {SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}.BIM360_ATTACHMENTS a
       ON a.issue_id = v."issue_id"
      AND a.project_id = v."project_id"
WHERE  v."project_id" = '{SNOWFLAKE_PROJECT_ID}'
"""

BIM360_ORIGIN = "https://bim360field.autodesk.com"

DOWNLOAD_TIMEOUT_MS = 60_000

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("fetch_photos.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def load_private_key_der_from_jks() -> bytes:
    if not SNOWFLAKE_JKS_PASSWORD:
        raise RuntimeError("Missing SNOWFLAKE_JKS_PASSWORD for keypair authentication.")

    created_temp_file = False
    if SNOWFLAKE_JKS_B64.strip():
        jks_path = Path(tempfile.gettempdir()) / f"snowflake_{uuid.uuid4().hex}.jks"
        jks_path.write_bytes(base64.b64decode(SNOWFLAKE_JKS_B64))
        created_temp_file = True
    else:
        jks_path = Path(SNOWFLAKE_JKS_PATH)
        if not jks_path.is_absolute():
            jks_path = Path.cwd() / jks_path
    if not jks_path.exists():
        raise FileNotFoundError(f"JKS file not found: {jks_path}")

    try:
        jks = importlib.import_module("jks")
    except ImportError:
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

    finally:
        if created_temp_file:
            try:
                jks_path.unlink(missing_ok=True)
            except Exception:
                pass

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
    return private_key.private_bytes(
        encoding=Encoding.DER,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )


def snowflake_rows():
    """Yield attachment rows from Snowflake.

    Yields:
        tuple[str, str, str, str]:
            (attachment_url, file_name, issue_id, project_id)
    """
    log.info("Connecting to Snowflake with keypair authentication …")
    conn_kwargs = {
        "account": SNOWFLAKE_ACCOUNT,
        "user": SNOWFLAKE_USER,
        "role": SNOWFLAKE_ROLE,
        "warehouse": SNOWFLAKE_WAREHOUSE,
        "database": SNOWFLAKE_DATABASE,
        "schema": SNOWFLAKE_SCHEMA,
        "private_key": load_private_key_der_from_jks(),
    }
    if SNOWFLAKE_AZURE_SAS_TOKEN:
        conn_kwargs["credentials"] = {"azure_sas_token": SNOWFLAKE_AZURE_SAS_TOKEN}

    con = snowflake.connector.connect(
        **conn_kwargs,
    )
    try:
        cur = con.cursor()
        cur.execute(SQL)
        rows = cur.fetchall()
        log.info("Snowflake returned %d rows.", len(rows))
        log.info("Snowflake project filter: %s", SNOWFLAKE_PROJECT_ID)
        for row in rows:
            yield row          # (url, file_name, issue_id, project_id)
    finally:
        con.close()


def blob_path(project_id: str, issue_id: str, file_name: str) -> str:
    """Build a deterministic blob name from row fields.

    Uses only the base filename to avoid path traversal or nested path surprises.
    """
    safe_name = PurePosixPath(file_name).name or "attachment"
    return f"{project_id}/{issue_id}/{safe_name}"


def upload_to_blob(blob_client, data: bytes, content_type: str) -> None:
    """Upload bytes to Azure Blob and set content type metadata."""
    blob_client.upload_blob(
        data,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
    )


def content_type_for(file_name: str) -> str:
    """Infer content type from file name, with a binary fallback."""
    ct, _ = mimetypes.guess_type(file_name)
    return ct or "application/octet-stream"


def download_attachment(url: str) -> bytes:
    """Download bytes directly from a public attachment URL."""
    request = Request(url, headers={"User-Agent": "clasicfieldphoto-fetch/1.0"})
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT_MS / 1000) as response:
        return response.read()


def main():
    """Run the end-to-end sync: Snowflake -> BIM360 download -> Azure Blob."""
    rows = list(snowflake_rows())

    service = BlobServiceClient.from_connection_string(AZURE_CONN_STR)
    container = service.get_container_client(AZURE_CONTAINER)
    try:
        container.create_container()
        log.info("Created blob container '%s'.", AZURE_CONTAINER)
    except Exception:
        pass  # already exists

    log.info("Using public attachment URLs directly; no BIM360 SSO browser login is required.")

    ok = skipped = failed = 0

    for url, file_name, issue_id, project_id in rows:
        blob_name = blob_path(project_id, issue_id, file_name)
        blob_client = container.get_blob_client(blob_name)

        # Skip if already uploaded
        try:
            blob_client.get_blob_properties()
            log.info("SKIP  (exists) %s", blob_name)
            skipped += 1
            continue
        except Exception:
            pass

        if not url:
            log.warning("SKIP  (no URL) issue_id=%s  file=%s", issue_id, file_name)
            skipped += 1
            continue

        # Download directly from the public URL
        try:
            data = download_attachment(url)
        except Exception as exc:
            log.error("FAIL  download  %s  →  %s", url, exc)
            failed += 1
            continue

        # Upload to blob storage
        try:
            upload_to_blob(blob_client, data, content_type_for(file_name))
            log.info("OK    %s  (%d bytes)", blob_name, len(data))
            ok += 1
        except Exception as exc:
            log.error("FAIL  upload    %s  →  %s", blob_name, exc)
            failed += 1

    log.info("Done — uploaded: %d  skipped: %d  failed: %d", ok, skipped, failed)


if __name__ == "__main__":
    main()
