import pytest

from scripts import ingesta_server


@pytest.mark.parametrize("page,schema", [
    ("vina", "vina_view_v1"),
    ("curico", "curico_view_v1"),
    ("sucden", "sucden_view_v1"),
    ("inmosa", "inmosa_view_v1"),
])
def test_single_asset_view_requires_session_and_exposes_its_contract(page, schema):
    ingesta_server.app.config["TESTING"] = True
    client = ingesta_server.app.test_client()

    assert client.get(f"/reports/{page}").status_code == 302
    response = client.get(f"/api/reports/{page}", headers={"X-Analyst-Test-User-Id": "report-user"})
    assert response.status_code == 200
    assert response.get_json()["schema_version"] == schema
