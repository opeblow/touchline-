"""Touchline serverless automation (Azure Functions, Python v2 model, Flex Consumption).

Event-driven companions to the live pipeline. Every binding uses the app's
managed identity; there are no connection strings.

  archive_events   Event Hubs trigger (consumer group "functions"). Archives every
                   match event to Cosmos DB (container "events", partition /match_id),
                   giving a durable, replayable record of each match. On half time and
                   full time it notifies the Logic App (e.g. a Microsoft Teams channel).
  nightly_season   Timer trigger (03:00 UTC). Starts the Container Apps Job that
                   regenerates the 380-match synthetic season.
  health           HTTP probe.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

import azure.functions as func

app = func.FunctionApp()
log = logging.getLogger("touchline.functions")


@app.event_hub_message_trigger(
    arg_name="events",
    event_hub_name="%EVENTHUB_NAME%",
    connection="EventHubConnection",
    consumer_group="functions",
    cardinality="many",
)
@app.cosmos_db_output(
    arg_name="archive",
    database_name="%COSMOS_DB%",
    container_name="events",
    connection="CosmosConnection",
)
def archive_events(events: list[func.EventHubEvent], archive: func.Out[func.DocumentList]) -> None:
    docs = func.DocumentList()
    phases = []
    for e in events:
        try:
            body = json.loads(e.get_body().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            log.warning("Skipping malformed event")
            continue
        if body.get("type") == "__end__" or "event_id" not in body:
            continue
        body["id"] = body["event_id"]
        docs.append(func.Document.from_dict(body))
        if body.get("type") in ("half_end", "match_end"):
            phases.append(body)
    if docs:
        archive.set(docs)
    for p in phases:
        notify_phase(p)
    log.info("Archived %d events (%d phase changes)", len(docs), len(phases))


def notify_phase(event: dict) -> None:
    """Post half-time / full-time to the Logic App (Teams, email, ...)."""
    url = os.environ.get("LOGIC_APP_URL")
    if not url:
        return
    score = event.get("extra", {}).get("score", [0, 0])
    phase = "Full time" if event.get("type") == "match_end" else "Half time"
    payload = {
        "match_id": event.get("match_id"),
        "headline": f"{phase}: {score[0]}-{score[1]}",
        "standfirst": "Automated phase notification from Touchline (Azure Functions)",
        "body_md": f"Match {event.get('match_id')} reached {phase.lower()} at minute {event.get('minute')}.",
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as exc:  # noqa: BLE001 - notification must never fail the archive
        log.warning("Logic App notification failed: %s", exc)


@app.timer_trigger(arg_name="timer", schedule="0 0 3 * * *", run_on_startup=False)
def nightly_season(timer: func.TimerRequest) -> None:
    """Start the season-regeneration Container Apps Job via Azure Resource Manager."""
    job_id = os.environ.get("SEASON_JOB_ID")
    if not job_id:
        log.info("SEASON_JOB_ID not set; skipping")
        return
    from azure.identity import DefaultAzureCredential

    token = DefaultAzureCredential().get_token("https://management.azure.com/.default").token
    req = urllib.request.Request(
        f"https://management.azure.com{job_id}/start?api-version=2024-03-01",
        data=b"{}",
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        log.info("Season job started: HTTP %s", r.status)


@app.route(route="health", auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(json.dumps({"ok": True, "service": "touchline-functions"}), mimetype="application/json")
