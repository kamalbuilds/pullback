"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Queue" },
  { href: "/activity", label: "Activity" },
];

export function Masthead() {
  const pathname = usePathname();

  return (
    <header className="border-b border-rule">
      <div className="mx-auto flex h-[68px] w-full max-w-[1080px] items-center justify-between px-6">
        <Link href="/" className="flex items-baseline gap-3">
          <span
            className="text-[21px] leading-none"
            style={{ fontVariationSettings: '"opsz" 24', letterSpacing: "-0.01em" }}
          >
            Pullback
          </span>
          <span className="label hidden sm:inline">recall desk</span>
        </Link>
        <nav className="flex items-center gap-6">
          {LINKS.map((link) => {
            const active =
              link.href === "/" ? pathname === "/" || pathname.startsWith("/case") : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className="label"
                style={{
                  color: active ? "var(--ink)" : "var(--ink-3)",
                  borderBottom: active ? "1px solid var(--seal)" : "1px solid transparent",
                  paddingBottom: "4px",
                }}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
