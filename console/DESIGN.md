# Pullback console design system

## The one thing this interface has to do

Pullback runs on a schedule without being opened. The console is not where the work happens,
it is where the work surfaces when a person has to decide something. So the interface is
graded on its empty state first and its dense state second. Every decision below follows from
that: an empty queue must read as a finished night shift, not as an app with nothing in it.

The reader is a parent. In the 2026 CPSC corpus this agent screens against, 317 of 434 recall
titles contain the word "death". The register is a public notice, calm and exact. Not a
dashboard, not a wellness app, not cute.

## Type

Two families. The split carries the argument: the serif is what the agent says, the mono is
what the agent can prove.

| Family | Role |
|---|---|
| Newsreader (variable, 400/500, optical sizing on) | statements, hazards, prose, headlines |
| IBM Plex Mono (400/500) | every fact: dates, prices, ids, check details, labels, buttons |

Newsreader is a screen news serif, not a display serif. It is chosen because a recall notice
is a published record and this product's whole claim is that it read one correctly. Fraunces
and Instrument Serif are banned. There is no sans in this system.

### Scale

| Token | Size / line | Family | Used for |
|---|---|---|---|
| `--t-statement` | clamp(30px, 2.2vw + 18px, 42px) / 1.1 | Newsreader 400 | empty-state report, case headline |
| `--t-record` | 25px / 1.2 | Newsreader 400 | one queue record's subject |
| `--t-hazard` | 18px / 1.45 | Newsreader 400 | the hazard sentence |
| `--t-prose` | 16px / 1.6 | Newsreader 400 | body, secondary statements |
| `--t-data` | 13px / 1.55 | Plex Mono 400 | check details, timeline detail, claim text |
| `--t-label` | 10.5px / 1 | Plex Mono 500, `0.11em` tracking, uppercase | section labels, field names |
| `--t-micro` | 11.5px / 1.4 | Plex Mono 400 | timestamps, case ids, counts |

Numerals are always `tabular-nums` in mono. Prices, dates and counts never render in the serif.

## Color roles

One accent (`--seal`), two semantic states (`--alarm`, `--pending`). The accent is a green
because the product's argument is that most things get closed without you; green is the
resolved state and the primary action, and it is never used for hazard. Hazard owns oxblood
and nothing else owns oxblood.

| Role | Light | Dark | Meaning |
|---|---|---|---|
| `--paper` | `#F3F4F2` | `#121417` | page |
| `--sheet` | `#FCFCFB` | `#191C20` | a record, a panel |
| `--sheet-2` | `#EEEFEC` | `#1F2328` | inset block, claim letter, code |
| `--ink` | `#15181A` | `#E8EAE7` | primary text |
| `--ink-2` | `#454B4D` | `#A8AEAC` | secondary prose |
| `--ink-3` | `#6E7573` | `#7C8481` | labels, timestamps |
| `--rule` | `#DEE0DB` | `#2A2E33` | hairline between records |
| `--rule-strong` | `#C4C8C1` | `#3A3F45` | input border, table head rule |
| `--seal` | `#1B4B3A` | `#5FA98C` | agent action, resolved, primary button |
| `--on-seal` | `#F7FAF8` | `#0E1512` | text on the accent |
| `--alarm` | `#8C1D18` | `#E08078` | hazard sentence, failed check |
| `--pending` | `#7A5210` | `#D3A24E` | waiting on a person |

No pure black, no pure white. Backgrounds are cool neutral, deliberately not the cream and
brass palette that every generated "trustworthy" page reaches for.

## Space and shape

4px base unit. Steps used: 4, 8, 12, 16, 24, 32, 48, 64, 96.
Container is a single reading column, `max-width: 1080px`, `padding-inline: 24px`.
Vertical rhythm between queue records is a 1px `--rule`, not a gap. Records are sheets of one
document, not floating cards.

Radius is `4px` everywhere. Status marks are `2px`. Nothing is a pill, nothing is a circle.
Elevation is expressed with a hairline border and a background shift, never a drop shadow.

## Components and their states

### Record (a queue row)

Anatomy, top to bottom, in the order a person needs it:
status mark and age, the subject in serif, the hazard in `--alarm`, the agent's decision line
in mono, and exactly one action.

| State | Treatment |
|---|---|
| rest | `--sheet`, 1px `--rule` bottom, `padding: 32px 0` |
| hover | background `--sheet-2`, action underline appears |
| focus-visible | 2px `--seal` outline, 2px offset, on the whole record link |
| pressed | `translateY(1px)` |
| disabled action | `--ink-3` text, `cursor: not-allowed`, native `title` states the real reason |

### Status mark

A 2px square in the state colour plus a mono uppercase word. No coloured dots, no pills.
`needs you` = `--pending`, `sent` = `--ink-2`, `closed` = `--seal`, `no match` = `--ink-3`.

### Check row (the audit trail)

Grid: `[mark] [name, mono] [detail, mono, tabular]`. Passed rows use `--ink` on `--sheet`.
Failed rows use `--alarm` for the mark and the name, and carry a 2px left rule in `--alarm`.
The detail is never paraphrased. It is the string the engine produced.

### Buttons

| Variant | Rest | Hover | Focus | Disabled |
|---|---|---|---|---|
| primary | `--seal` fill, `--on-seal` text, mono uppercase 11px | brightness 1.08 | 2px offset `--seal` ring | 40% opacity, real reason in `title` |
| secondary | transparent, 1px `--rule-strong`, `--ink` | border `--ink-3` | same ring | same |
| destructive | transparent, 1px `--alarm`, `--alarm` text | `--alarm` 6% wash | ring in `--alarm` | same |

Labels are two words at most and never wrap.

### Input (evidence form)

Label above in `--t-label`, input `--sheet-2` with 1px `--rule-strong`, focus ring 2px `--seal`.
Helper text below in `--t-micro` `--ink-3`. Error text below in `--alarm`. No placeholder as label.
Contrast of every text-on-background pair here clears WCAG AA.

### Empty queue

Not a component, the point of the product. A single serif statement, then a mono report of
what ran while the person was away, then the case count that closed without them. Every number
in it is read from the cases table, never a constant. The button under it triggers a real agent
run, and is disabled with a stated reason when `PULLBACK_AGENT_URL` is unset.

## Motion

`MOTION_INTENSITY 2`. Three animations exist in the whole console.

1. Record hover background, 120ms ease-out. Feedback.
2. Button press `translateY(1px)`, 80ms. Feedback.
3. Empty-state report fades up 8px over 420ms on load. Storytelling: the report is the answer
   to the question the person opened the page with.

Everything collapses to instant under `prefers-reduced-motion: reduce`. No scroll hijack, no
marquee, no parallax, no skeleton shimmer, no spinners.

## Rules this console holds itself to

- Zero em dashes anywhere in copy or code.
- No hardcoded case data in any component. Every figure on screen came out of DynamoDB in a
  server component, and the number a person reads can be traced to a row.
- No emoji, no icon library, no decorative SVG. The only glyphs are type.
- One action per record. A row of buttons is a product that has not decided what matters.
- Empty states say what happened, never "No data".
- Each route owns its own `<title>` from a server component.
