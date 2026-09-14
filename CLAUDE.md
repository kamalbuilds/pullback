# Pullback

An agent that finds out whether something in a household has been recalled, then
gets the manufacturer's remedy delivered. Submitted to the AWS Agents for Humans
hackathon, Everyday Agents track, deadline 2026-09-14 17:00 PT.

## The one idea

Recall notices are prose, not data. Measured across all 434 CPSC notices from
2026 (`python scripts/measure_feed.py`): 3% carry a UPC, 0% carry a model
number, but 94% state a sold-at window, 94% state a price band and 92% print a
remedy contact. So identity has to be read, and eligibility has to be computed.

## The rule that must never be broken

The model reads identity. The model never decides eligibility.

- `agent/engine/verdict.py` decides, using dates, money and identifiers. No
  prompt reaches it. Returns MATCH / NEEDS_EVIDENCE / NO_MATCH.
- `judge_identity` accepts the model's read but returns the computed verdict.
- `RemedyVeto` in `agent/pullback_agent.py` is a Strands `BeforeToolCallEvent`
  hook that cancels `dispatch_remedy` unless the ledger holds a MATCH verdict
  and a written claim for that exact case.

`tests/test_veto.py::test_the_hook_cancels_a_dispatch_that_is_actually_attempted`
is the test that proves it. Remove the hook and it goes red by filing a real
claim for a product the household does not own. Never weaken that test to make
a change pass.

An `IdentityAssertion` may only replace the soft lexical `description_overlap`
check. It can never touch retailer, sold window, price band or UPC.

## Environment

- Python 3.12 venv at `.venv`. Run from the repo root.
- `.env` holds `ANTHROPIC_API_KEY`. Never print it, never commit it.
- AWS: profile `palimpsest`, region us-east-1. Always
  `export AWS_PROFILE=palimpsest AWS_DEFAULT_REGION=us-east-1` and
  `unset AWS_BEARER_TOKEN_BEDROCK` first.
- **Bedrock and AgentCore do not work on this account.** It is an AWS India
  (AISPL) account, where Bedrock is not offered. Every model in every region
  returns `Operation not allowed`, for the account administrator too. Do not
  spend time trying to fix this. Strands is model-agnostic, so the agent runs on
  Anthropic directly while Lambda, EventBridge Scheduler, DynamoDB and S3 carry
  the rest.

## Live resources

- DynamoDB `pullback-cases` (PK household, SK case_id), `pullback-recalls`
- S3 `pullback-evidence-079415246611`
- IAM role `pullback-exec`, Lambda `pullback-run`

## Data honesty

`data/household.json` is a representative household, and the README says so.
The recalls it is checked against are always live. Never write a case by hand
into DynamoDB to make a demo look better: cases must come from a real run, or
the console is showing fiction. If you find hand-written cases in the table,
delete them and rerun `python -m agent.run --live --dynamo`.

## House style

No em dashes. No decorative comments. Comments justify non-obvious decisions
only. Production code only: no mocks, no stubs, no placeholder data. Tests run
against real captured API responses in `data/`, never invented fixtures.
