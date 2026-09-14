import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Pullback: no such case",
};

export default function NotFound() {
  return (
    <section className="pt-24">
      <h1 className="statement max-w-[20ch]">No case with that id.</h1>
      <p className="prose-16 mt-6 max-w-[54ch]" style={{ color: "var(--ink-2)" }}>
        Case ids are written by the agent when a purchase matches a notice. This one is not in
        this household, or it was never opened.
      </p>
      <p className="mt-8">
        <Link href="/" className="btn btn-secondary">
          Back to the queue
        </Link>
      </p>
    </section>
  );
}
