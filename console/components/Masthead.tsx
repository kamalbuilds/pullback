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
    <header className="board">
      <div className="board-inner mx-auto w-full max-w-[1120px] px-5 sm:px-7">
        <Link href="/" className="flex items-baseline gap-3">
          <span className="wordmark">Pullback</span>
          <span className="label hidden sm:inline">recall desk</span>
        </Link>
        <nav className="flex items-center gap-6">
          {LINKS.map((link) => {
            const active =
              link.href === "/"
                ? pathname === "/" || pathname.startsWith("/case")
                : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className="label nav-link"
                data-active={active}
                style={{ color: active ? "var(--ink)" : "var(--ink-3)" }}
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
