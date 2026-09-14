import type { Metadata } from "next";
import { Archivo, Space_Mono } from "next/font/google";

import { Masthead } from "@/components/Masthead";

import "./globals.css";

const archivo = Archivo({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-archivo",
});

const spaceMono = Space_Mono({
  subsets: ["latin"],
  weight: ["400", "700"],
  display: "swap",
  variable: "--font-space-mono",
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
    <html lang="en" className={`${archivo.variable} ${spaceMono.variable}`}>
      <body>
        <Masthead />
        <main className="mx-auto w-full max-w-[1120px] px-5 pb-24 sm:px-7">{children}</main>
      </body>
    </html>
  );
}
