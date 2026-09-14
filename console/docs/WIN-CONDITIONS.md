# Pullback win conditions

Scope note: written by the console agent for the Agents for Humans hackathon
(agentsforhumans.devpost.com, deadline 2026-09-15 05:30 GMT+5:30, 9,772 registered
participants). Every line below is checkable against a URL, a file path or a DynamoDB row.

Scoreboard: first edition of this event, so there is no prior winner list to name. The
comparable set is the live gallery at agentsforhumans.devpost.com/project-gallery, judged on
five equally weighted criteria, of which Design is one.

Bar to beat: 5 of 5 on Design, which is 20% of the total score. Concretely, a judge opening
the deployed console reaches a decision, sees the four named checks with the real values they
compared, and clicks through to the cpsc.gov notice the verdict cites, in under 30 seconds and
zero scrolls past the first record.

Asset we will own: the parsed CPSC constraint corpus. 434 notices from the 2026 SaferProducts
feed reduced to machine-checkable constraints (sold window, price band, retailer list, UPC,
model) by agent/feeds/cpsc.py. 94% of those notices yield a sold window and 99% yield a price.
The CPSC API publishes prose; nobody publishes these as fields.

Off-platform buyer: a parent of a toddler with an Amazon and a Target order history who has
never opened a recall notice in their life and does not know the CPSC exists.

Single entry: Pullback.

Verb the brief names: "handles repetitive tasks", from the event line "Build an AI agent with
Strands Agents SDK that handles repetitive tasks".

Our product performs that verb: yes. agent/engine/verdict.py returns MATCH, NEEDS_EVIDENCE or
NO_MATCH from arithmetic on dates, money and identifiers, and console/app/api/cases/[case_id]/route.ts
writes the approval to DynamoDB and hands the case to the agent endpoint for dispatch. The
timeline carries claim.dispatched, manufacturer.replied and remedy.confirmed, so the product
drives a refund to completion rather than stopping at a recommendation.

Metric plan: cases closed without a human. Target 8 of every 10 screened purchases resolved
with no queue entry. Checked on /activity and countable directly in DynamoDB table
pullback-cases, where a closed case carries no approval.granted or evidence.provided event.

Live by: 2026-09-14, roughly 15 hours before the deadline. This misses the seven day rule in
the canonical gate, and that is a real deviation, not a rounding. The build started the day
before the deadline.

Deviation from research: the seven day live-by target above was missed, stated rather than
hidden. Nothing else deviates.
