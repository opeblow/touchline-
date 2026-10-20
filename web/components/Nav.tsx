"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/live?match=demo", path: "/live", label: "Live match" },
  { href: "/overlay?match=demo&bg=pitch", path: "/overlay", label: "Broadcast overlay" },
  { href: "/control?match=demo", path: "/control", label: "Control room" },
  { href: "/recap?match=demo", path: "/recap", label: "Recap" },
  { href: "/studio", path: "/studio", label: "Data studio" },
];

export function Wordmark() {
  return (
    <Link href="/" className="wordmark" aria-label="Touchline home">
      <span className="wordmark-mark" aria-hidden />
      TOUCHLINE
    </Link>
  );
}

export default function Nav({ right }: { right?: React.ReactNode }) {
  const path = usePathname();
  return (
    <header className="nav">
      <div className="container nav-inner">
        <Wordmark />
        <nav className="nav-links" aria-label="Primary">
          {LINKS.map((l) => (
            <Link key={l.path} href={l.href} className={`nav-link ${path?.startsWith(l.path) ? "active" : ""}`}>
              {l.label}
            </Link>
          ))}
        </nav>
        <div className="row" style={{ marginLeft: "auto" }}>
          {right ?? (
            <Link href="/live?match=demo" className="btn small">
              Watch live
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
