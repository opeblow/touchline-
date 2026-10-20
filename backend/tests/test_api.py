from fastapi.testclient import TestClient

from touchline.api.main import app


def test_health_league_and_schema():
    with TestClient(app) as c:
        assert c.get("/api/health").json()["ok"] is True
        assert len(c.get("/api/league").json()) == 20
        schema = c.get("/api/schema/overlay").json()
        assert {"cue_id", "template", "t_in", "t_out"} <= set(schema["properties"])
        assert c.get("/api/matches/nope").status_code == 404
