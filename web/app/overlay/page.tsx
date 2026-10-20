"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import OverlayStage from "@/components/OverlayStage";
import Stadium3D from "@/components/Stadium3D";
import { playersById } from "@/lib/format";
import { useMatch, type Prefs } from "@/lib/useMatch";

/**
 * Broadcast overlay. Add as an OBS / vMix browser source at 1920×1080:
 *   /overlay?match=demo&bg=transparent   graphics only, transparent background
 *   /overlay?match=demo&bg=pitch         graphics over the live 2D pitch (demo)
 * Everything on screen is driven by timed overlay cues (overlay.schema.json).
 */
function Overlay() {
  const params = useSearchParams();
  const matchId = params.get("match") || "demo";
  const bg = params.get("bg") || "pitch";
  const lang = params.get("lang") || "en";
  const [prefs] = useState<Prefs>({ mode: "fan", lang, club: null, player_id: null });
  const { state, control } = useMatch(matchId, prefs, { frames: bg === "pitch" });
  const players = useMemo(() => playersById(state.meta), [state.meta]);

  useEffect(() => {
    if (bg === "transparent") {
      document.body.style.background = "transparent";
      document.documentElement.style.background = "transparent";
    } else {
      document.body.style.background = "#0b120e";
    }
  }, [bg]);

  const meta = state.meta;
  if (!meta) return null;
  const home = { code: meta.home.code, color: meta.home.primary };
  const away = { code: meta.away.code, color: meta.away.primary };
  const status = state.status?.status;
  return (
    <main style={{ width: "100vw", minHeight: "100vh", display: "grid", placeItems: "center" }}>
      <div style={{ width: "min(100vw, calc(100vh * 16 / 9))" }}>
        <OverlayStage
          cues={state.cues} now={state.now} minute={state.stats?.minute ?? 0} period={state.stats?.period ?? 1}
          score={(state.stats?.score ?? [0, 0]) as [number, number]} home={home} away={away} finished={status === "finished"}
          background={bg === "pitch" ? (
            <div style={{ position: "absolute", inset: 0 }}>
              <Stadium3D frame={state.frame} ids={state.ids} players={players} homeColor={home.color} awayColor={away.color} showControls={false} events={state.events} speed={state.status?.speed} />
            </div>
          ) : undefined}
        />
      </div>
      {bg !== "transparent" && (status === "ready" || status === "paused") && (
        <button className="btn green" style={{ position: "fixed", bottom: 20, right: 20 }} onClick={() => control(status === "paused" ? "resume" : "start", 8)}>
          Start feed
        </button>
      )}
    </main>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Overlay />
    </Suspense>
  );
}
