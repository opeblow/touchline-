import type { Metadata, Viewport } from "next";
import { Barlow_Condensed, Inter, JetBrains_Mono, Source_Serif_4 } from "next/font/google";
import "./globals.css";

const barlow = Barlow_Condensed({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--f-barlow" });
const inter = Inter({ subsets: ["latin"], variable: "--f-inter" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--f-mono" });
const serif = Source_Serif_4({ subsets: ["latin"], weight: ["400", "600", "700"], variable: "--f-serif" });

export const metadata: Metadata = {
  title: "Touchline — explainable match intelligence",
  description:
    "Touchline turns live football events into broadcast graphics, explanations and recaps — personalised for every fan, in every language, with every number checked.",
};

export const viewport: Viewport = { themeColor: "#f5f3ee", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${barlow.variable} ${inter.variable} ${mono.variable} ${serif.variable}`}>
      <body>{children}</body>
    </html>
  );
}
