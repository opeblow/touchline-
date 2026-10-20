import { clockLabel } from "@/lib/format";

interface Props {
  home: { code: string; color: string };
  away: { code: string; color: string };
  score: [number, number];
  minute: number;
  period: number;
  size?: "md" | "lg";
  finished?: boolean;
}

export default function ScoreBug({ home, away, score, minute, period, size = "md", finished }: Props) {
  return (
    <div className={`scorebug ${size === "lg" ? "lg" : ""}`} role="status" aria-label={`${home.code} ${score[0]}, ${away.code} ${score[1]}`}>
      <span className="swatch" style={{ background: home.color }} />
      <span className="team">{home.code}</span>
      <span className="score">
        {score[0]}
        <span style={{ opacity: 0.35, margin: "0 6px" }}>–</span>
        {score[1]}
      </span>
      <span className="team">{away.code}</span>
      <span className="swatch" style={{ background: away.color }} />
      <span className="clock">{finished ? "FT" : clockLabel(minute, period)}</span>
    </div>
  );
}
