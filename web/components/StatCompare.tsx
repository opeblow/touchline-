import type { TeamStats } from "@/lib/types";

const ROWS: { key: keyof TeamStats; label: string; digits?: number; unit?: string; lowerBetter?: boolean }[] = [
  { key: "possession", label: "Possession", digits: 0, unit: "%" },
  { key: "xg", label: "Expected goals (xG)", digits: 2 },
  { key: "shots", label: "Shots" },
  { key: "shots_on_target", label: "On target" },
  { key: "pass_accuracy", label: "Pass accuracy", digits: 0, unit: "%" },
  { key: "ppda", label: "PPDA (press, lower = harder)", digits: 1, lowerBetter: true },
  { key: "field_tilt", label: "Field tilt", digits: 0, unit: "%" },
  { key: "distance_km", label: "Distance (km)", digits: 1 },
  { key: "sprints", label: "Sprints" },
];

export default function StatCompare({ home, away, homeColor, awayColor, compact }: {
  home: TeamStats; away: TeamStats; homeColor: string; awayColor: string; compact?: boolean;
}) {
  const rows = compact ? ROWS.slice(0, 6) : ROWS;
  return (
    <div>
      {rows.map((r) => {
        const h = Number(home[r.key] ?? 0), a = Number(away[r.key] ?? 0);
        let hs = h, as = a;
        if (r.lowerBetter) { hs = a; as = h; }
        const total = hs + as || 1;
        const hw = (hs / total) * 100;
        const fmt = (v: number) => `${v.toFixed(r.digits ?? 0)}${r.unit ?? ""}`;
        return (
          <div className="statrow" key={r.key}>
            <span className="v">{fmt(h)}</span>
            <div className="mid">
              <span className="lbl">{r.label}</span>
              <div className="bars">
                <span style={{ width: `${hw}%`, background: homeColor }} />
                <span style={{ width: `${100 - hw}%`, background: awayColor }} />
              </div>
            </div>
            <span className="v r">{fmt(a)}</span>
          </div>
        );
      })}
    </div>
  );
}
