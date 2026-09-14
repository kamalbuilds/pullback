# Pullback console design system: the hang tag

## The one thing this interface has to do

Pullback runs on a schedule without being opened. The console is where work surfaces when a
person has to decide something, so it is graded on its empty state first and its dense state
second. An empty queue reads as a finished night shift, never as an app with nothing in it.

The reader is a parent. In the 2026 CPSC corpus this agent screens against, 317 of 434 recall
titles contain the word "death". The register is a product safety notice: exact, unhurried, not
cute.

## The metaphor

A recall notice arrives as prose about an object. This console renders the object back. Every
case is a **swing tag**, the kind stapled through a toy at the store: a cut corner, a punched
hole with its reinforcing ring, a perforated header carrying the notice number, a stamped hazard
band, and a spec block with dotted leaders. Nothing on the page is a dashboard card.

Three consoles in this family must never look like one product with three datasets:

| Axis | Pullback | Lapse | Best By |
|---|---|---|---|
| Metaphor | swing tag on the object | cyanotype drawing sheet | stamped case and dual sheets |
| Paper | bone, light only | blueprint blue, dark only | warm carton kraft |
| Type | Archivo + Space Mono | Barlow Condensed + Barlow + IBM Plex Mono | Literata + JetBrains Mono |
| Action | ink black fill | chalk white fill | indigo stamp fill |
| Layout | two-up tag grid | ruled sheet with dimension lines | persistent SHELF / KITCHENS split |
| Radius | 2px | 0 | 0 to 1px |

Banned here because a sibling owns them: any serif, IBM Plex Mono, JetBrains Mono, a single
hairline document spine as the home layout, a blue or indigo primary, a printed grid ground.

## Light only

A hang tag is paper. Paper has no dark mode, so `color-scheme: light` is declared and there is
no `prefers-color-scheme` block. The bone ground carries a 2% crossing weave at 4px so it reads
as stock rather than as a flat fill.

## Type

| Family | Role |
|---|---|
| Archivo (variable, 400/500/600) | statements, tag titles, hazard sentences, prose |
| Space Mono (400/700) | every fact: dates, prices, ids, spec values, check chips, buttons |

The split carries the argument: the sans is what the agent says, the mono is what it can prove.
No number a person compares is ever set in the sans.

| Token | Spec | Used for |
|---|---|---|
| `--t-statement` | clamp(30px, 2.4vw + 17px, 46px), Archivo 600, -0.028em | the count above the board, case headline |
| `--t-tag-title` | clamp(19px, 0.5vw + 17px, 22px), Archivo 500 | the thing on a tag |
| `.band` | 14.5px / 1.42, `--hazard` | the hazard sentence, and nothing else |
| `.data` | Space Mono 12.5px, tabular | check details, claim text, timeline detail |
| `.spec-key` | Space Mono 700 10px, 0.1em caps | spec labels on a tag |
| `.label` | Space Mono 700 10px, 0.15em caps | section labels, status marks |
| `.micro` | Space Mono 11px, tabular | timestamps, ids, counts |

## Colour

| Role | Value | Meaning |
|---|---|---|
| `--paper` | `#EFECE3` | the board the tags hang on |
| `--tag` | `#FFFDF8` | a tag, a panel |
| `--tag-2` | `#F6F2E8` | inset block, claim letter, chip |
| `--ink` | `#14161A` | primary text, and the primary button fill |
| `--ink-2` | `#4A4E54` | secondary prose |
| `--ink-3` | `#7E8188` | labels, timestamps |
| `--rule` | `#DDD7C9` | hairline inside a tag |
| `--rule-strong` | `#C2BBA8` | tag edge, input border |
| `--perf` | `#B8B0A0` | the dashed perforation under a tag header |
| `--hazard` | `#8C1D18` | hazard band, failed check, and nothing else |
| `--pending` | `#8A5A0B` | waiting on a person |
| `--clear` | `#2F5C3F` | passed check, resolved case, the CLEARED stamp |

The action colour is ink, not a hue. A parent pressing a black button on a paper tag is pressing
the only thing on the page that is not paper. Hazard owns oxblood; nothing else may use it.

## Shape and space

4px base. Steps: 4, 8, 12, 16, 18, 24, 32, 48, 54.
Container is `max-width: 1120px`, `padding-inline: 20px` rising to 28px.
Radius is 2px everywhere, with no second radius in the system. Nothing is a pill or a circle
except the punched hole, which is a hole.
Elevation is a 1px border plus a 1px hairline shadow at 4%, never a soft drop shadow.

## Components

### Tag (a queue record)

`clip-path` cuts the top left corner at 22px; `::before` draws the punched hole and its ring on
the cut. Header row: notice number left, status mark right, dashed `--perf` rule under it. Body:
title, hazard band, spec block, check chips. Foot: exactly one primary action, full width, with
the age and a link to the checks under it. Two per row at 860px and up, one below.

### Spec row

`label · dotted leader · value`, the way a real tag prints. Values are mono and tabular so two
tags side by side line up on the decimal.

### Check chip

One box per check the engine ran, mono caps, with a tick or a cross. Failed chips carry the
hazard border and wash. The chip's `title` is the exact string the engine produced, never a
paraphrase.

### Cleared tag (the empty queue)

The empty queue is the product working, so it gets the one piece of paper on the page: a tag with
nothing written on it but a rotated `CLEARED` stamp in `--clear`, the statement, and a mono
report of what ran while the person was away. Every number in it is read from the cases table.

### Buttons

Primary is `--ink` fill with `--on-ink` text, mono caps, full width inside a tag. Secondary is a
1px `--rule-strong` outline. Destructive is a hazard outline. Disabled keeps the shape, drops to
40% and states the real reason in `title`.

## Motion

Two animations exist. The empty-state report fades up 6px over 380ms, because the report is the
answer to the question the person opened the page with. Buttons translate 1px on press. Hover
changes colour only. Everything collapses under `prefers-reduced-motion: reduce`. No skeletons,
no spinners, no parallax, no scroll hijack.

## Rules this console holds itself to

- No em dashes anywhere in copy or code.
- No hardcoded case data in any component. Every figure came out of DynamoDB in a server
  component and traces to a row.
- No emoji, no icon library, no decorative SVG. The only glyphs are type, a tick, and a cross.
- One action per tag. A row of buttons is a product that has not decided what matters.
- Empty states say what happened, never "No data".
- Each route owns its own `<title>` from a server component.
