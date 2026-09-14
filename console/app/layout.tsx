import type { Metadata } from "next";
import { IBM_Plex_Mono, Newsreader } from "next/font/google";

import { Masthead } from "@/components/Masthead";

import "./globals.css";

const newsreader = Newsreader({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-newsreader",
  axes: ["opsz"],
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
  variable: "--font-plex-mono",
});

export const metadata: Metadata = {
  title: {
    default: "Pullback: recall decision queue",
    template: "%s",
  },
  description:
    "Pullback checks what is in your home against published recall notices and drives the manufacturer's remedy to completion. The console only shows the decisions that need a person.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${newsreader.variable} ${plexMono.variable}`}>
      <body>
        <Masthead />
        <main className="mx-auto w-full max-w-[1080px] px-6 pb-24">{children}</main>
      </body>
    </html>
  );
}
