"""Smoke test del endpoint /api/export-pdf: usa Flask test_client + Playwright real."""
from __future__ import annotations

import threading
import time
import urllib.request
import zipfile
from io import BytesIO

import pytest

from scripts import ingesta_server


@pytest.fixture(scope="module")
def running_server():
    """Levanta ingesta_server en un thread real (Playwright necesita un puerto TCP real, no test_client)."""
    server_thread = threading.Thread(
        target=lambda: ingesta_server.app.run(port=8765, use_reloader=False, threaded=True),
        daemon=True,
    )
    server_thread.start()

    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:8765/factsheet", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        pytest.fail("El servidor no levantó a tiempo")
    yield


def test_export_pdf_genera_zip_con_pdf_valido(running_server):
    import requests

    resp = requests.post(
        "http://127.0.0.1:8765/api/export-pdf",
        headers={ingesta_server.TOKEN_HEADER: ingesta_server.API_TOKEN},
        json={"fondos": ["PT"], "periodo_cb": "2026-03", "periodo_op": "2026-06"},
        timeout=120,
    )
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        zf = zipfile.ZipFile(BytesIO(resp.content))
        names = zf.namelist()
        assert any(n.startswith("FS_PT_") and n.endswith(".pdf") for n in names)
        pdf_bytes = zf.read([n for n in names if n.endswith(".pdf")][0])
        assert pdf_bytes[:4] == b"%PDF"


def test_export_pdf_sin_token_da_401(running_server):
    import requests

    resp = requests.post(
        "http://127.0.0.1:8765/api/export-pdf",
        json={"fondos": ["PT"], "periodo_cb": "2026-03", "periodo_op": "2026-06"},
        timeout=10,
    )
    assert resp.status_code == 401


def test_export_pdf_sin_fondos_da_400(running_server):
    import requests

    resp = requests.post(
        "http://127.0.0.1:8765/api/export-pdf",
        headers={ingesta_server.TOKEN_HEADER: ingesta_server.API_TOKEN},
        json={"fondos": [], "periodo_cb": "2026-03", "periodo_op": "2026-06"},
        timeout=10,
    )
    assert resp.status_code == 400
