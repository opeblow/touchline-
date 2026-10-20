"""Load the synthetic season into Azure AI Search for the Memory agent.

One document per player per matchday ("{player_id}-md{NN}") with cumulative totals,
so the Memory agent can answer "how many league goals before this match?" with a
single key lookup.

  python -m touchline.search_index   (needs SEARCH_ENDPOINT and az login / managed identity)
"""

from __future__ import annotations

import json

import httpx

from touchline.config import get_settings
from touchline.season import SEASON_DIR
from touchline.sim.league import build_league

INDEX = {
    "fields": [
        {"name": "id", "type": "Edm.String", "key": True},
        {"name": "player_id", "type": "Edm.String", "filterable": True},
        {"name": "name", "type": "Edm.String", "searchable": True},
        {"name": "team", "type": "Edm.String", "filterable": True, "facetable": True},
        {"name": "matchday", "type": "Edm.Int32", "filterable": True, "sortable": True},
        {"name": "goals", "type": "Edm.Int32", "sortable": True},
        {"name": "assists", "type": "Edm.Int32", "sortable": True},
        {"name": "apps", "type": "Edm.Int32"},
        {"name": "summary", "type": "Edm.String", "searchable": True},
    ]
}


def _headers(settings) -> dict[str, str]:
    if settings.search_key:
        return {"api-key": settings.search_key, "Content-Type": "application/json"}
    from azure.identity import DefaultAzureCredential

    token = DefaultAzureCredential().get_token("https://search.azure.com/.default").token
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def main() -> None:
    s = get_settings()
    if not s.search_endpoint:
        raise SystemExit("Set SEARCH_ENDPOINT")
    players = json.loads((SEASON_DIR / "players.json").read_text(encoding="utf-8"))
    names = {p.id: (p.name, t.short_name) for t in build_league() for p in t.players}
    h = _headers(s)
    base = f"{s.search_endpoint}/indexes/{s.search_index}"
    with httpx.Client(timeout=60) as c:
        c.put(
            base, params={"api-version": "2024-07-01"}, headers=h, json={"name": s.search_index, **INDEX}
        ).raise_for_status()
        docs = []
        for pid, p in players.items():
            name, team = names.get(pid, (pid, "?"))
            for md, v in p["by_md"].items():
                docs.append(
                    {
                        "@search.action": "mergeOrUpload",
                        "id": f"{pid}-md{int(md):02d}",
                        "player_id": pid,
                        "name": name,
                        "team": team,
                        "matchday": int(md),
                        "goals": v["g"],
                        "assists": v["a"],
                        "apps": v["apps"],
                        "summary": f"{name} ({team}): {v['g']} goals, {v['a']} assists in {v['apps']} appearances after matchday {md}.",
                    }
                )
        for i in range(0, len(docs), 1000):
            c.post(
                f"{base}/docs/index",
                params={"api-version": "2024-07-01"},
                headers=h,
                json={"value": docs[i : i + 1000]},
            ).raise_for_status()
    print(f"Indexed {len(docs)} season documents into {s.search_index}")


if __name__ == "__main__":
    main()
