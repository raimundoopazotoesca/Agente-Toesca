from scripts import ingesta_server


def test_apoquindos_view_requires_session_and_exposes_its_contract():
    ingesta_server.app.config["TESTING"] = True
    client = ingesta_server.app.test_client()

    assert client.get("/reports/apoquindos").status_code == 302
    response = client.get("/api/reports/apoquindos?period=2026-06", headers={"X-Analyst-Test-User-Id": "report-user"})
    assert response.status_code == 200
    assert response.get_json()["schema_version"] == "apoquindos_view_v1"
