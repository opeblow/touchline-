"""touchline CLI.

touchline serve                     run the API (+ web app if built)
touchline season [--matchdays 38]   generate the synthetic season
touchline match --home nbk --away hbc --seed 7 --preset comeback --out data/samples
touchline feed --match demo         publish a match to Event Hubs in real time (simulator container)
touchline eval                      evaluation harness (see touchline.evals)
touchline mcp [--http]              MCP server
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="touchline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    s = sub.add_parser("season")
    s.add_argument("--matchdays", type=int, default=38)
    s.add_argument("--events", action="store_true", help="also write every event stream (large)")
    s = sub.add_parser("match")
    s.add_argument("--home", default="nbk")
    s.add_argument("--away", default="hbc")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--preset", default="classic")
    s.add_argument("--prompt", default=None)
    s.add_argument("--out", default="data/samples")
    s = sub.add_parser("feed")
    s.add_argument("--match", default="demo")
    s.add_argument("--speed", type=float, default=1.0)
    sub.add_parser("eval")
    s = sub.add_parser("mcp")
    s.add_argument("--http", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("touchline.api.main:app", host=args.host, port=args.port)
    elif args.cmd == "season":
        from touchline.season import generate_season

        t = time.time()
        out = generate_season(args.matchdays, keep_events=args.events)
        print(f"Season written to {out} in {time.time() - t:.0f}s")
    elif args.cmd == "match":
        from touchline.sim import simulate_match
        from touchline.sim.league import get_team
        from touchline.sim.scenario import PRESETS, parse_scenario_text

        scenario = parse_scenario_text(args.prompt) if args.prompt else PRESETS[args.preset]
        data = simulate_match(
            get_team(args.home), get_team(args.away), seed=args.seed, scenario=scenario, with_tracking=False
        )
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{data.meta.match_id}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"meta": data.meta.model_dump(mode="json")}) + "\n")
            for e in data.events:
                f.write(e.model_dump_json() + "\n")
        print(f"{len(data.events)} events, final score {data.final_score()} → {path}")
    elif args.cmd == "feed":
        asyncio.run(_feed(args.match, args.speed))
    elif args.cmd == "eval":
        from touchline.evals import run

        run()
    elif args.cmd == "mcp":
        sys.argv = ["touchline-mcp"] + (["--http"] if args.http else [])
        from touchline.mcp_server import main as mcp_main

        mcp_main()


async def _feed(match_id: str, speed: float) -> None:
    """Standalone simulator: publishes a match's events to the bus at match pace."""
    from touchline.config import get_settings
    from touchline.live.bus import make_bus
    from touchline.live.catalog import get_featured

    data = get_featured(match_id)
    bus = make_bus(get_settings(), match_id)
    start = time.monotonic()
    for ev in data.events:
        wait = ev.t / speed - (time.monotonic() - start)
        if wait > 0:
            await asyncio.sleep(wait)
        await bus.publish(ev)
    await bus.close()
    print(f"Published {len(data.events)} events for {match_id} via {bus.kind}")


if __name__ == "__main__":
    main()
