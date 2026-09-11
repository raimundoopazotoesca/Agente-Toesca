from scripts import ingesta_server


def test_vacancy_report_redirects_anonymous_users_to_login():
    ingesta_server.app.config["TESTING"] = True
    client = ingesta_server.app.test_client()

    response = client.get("/reports/vacancy")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_vacancy_report_api_returns_versioned_contract_for_authenticated_user():
    ingesta_server.app.config["TESTING"] = True
    client = ingesta_server.app.test_client()

    response = client.get(
        "/api/reports/vacancy?fund=Apo&period=2026-06",
        headers={"X-Analyst-Test-User-Id": "report-user"},
    )

    assert response.status_code == 200
    assert response.get_json()["schema_version"] == "vacancy_report_v1"


def test_vacancy_report_api_accepts_an_asset_selection():
    ingesta_server.app.config["TESTING"] = True
    client = ingesta_server.app.test_client()

    response = client.get(
        "/api/reports/vacancy?fund=Apo&period=2026-06&asset=Apo4501",
        headers={"X-Analyst-Test-User-Id": "report-user"},
    )

    assert response.status_code == 200
    assert response.get_json()["context"]["asset"] == "Apo4501"
