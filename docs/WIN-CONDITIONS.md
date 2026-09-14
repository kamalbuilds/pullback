# Win conditions

Answered 2026-09-13 21:40 UTC, before the first line of product code. Updated
2026-09-14 with what the build actually proved.

Hackathon: Agents for Humans (AWS x Devpost), https://agentsforhumans.devpost.com/
Deadline: 2026-09-14 17:00 PT. Track: Everyday Agents.

    Scoreboard: No prior edition of this hackathon. Closest comparable Devpost winners built on Strands or Bedrock: Amanat (data governance, strands + granite + chainlit + auth0), CVAgent (bedrock + agentcore), Nova Insurance Claims AI (bedrock + streamlit), TradeWizard (dynamodb + aurora). The asset each owns is a domain rulebook encoded as deterministic checks, never a chat surface.
    Bar to beat: 10 prizes. 1 Grand at $10,000, plus Gold $5,000 / Silver $3,000 / Bronze $2,000 in each of three tracks. Judged on 5 published criteria with no published weights. Entry count not disclosed during the submission period (the gallery returns 0 until judging).
    Asset we will own: A constraint index built from live regulator feeds, obtained by calling saferproducts.gov/RestWebServices/Recall, api.nhtsa.gov/recalls and api.fda.gov enforcement with no auth. 739 notices indexed today: 434 CPSC, 5 NHTSA, 300 openFDA. The asset is the conversion of prose into machine-checkable constraints, measured at 94% sold-window and 94% price-band coverage on CPSC, and 45.7% lot-code plus 12% UPC coverage on openFDA.
    Off-platform buyer: A US parent of a child under 5 who bought from Amazon, Target or Home Depot in the last three years and has never returned a product registration card. 42% of 2026 CPSC recalls are child-related and 317 of 434 titles contain the word death.
    Single entry: Pullback. One product, one track.
    Verb the brief names: "handles routine and repetitive tasks in the background", "runs autonomously and only surfaces when there's a real decision to make", "does real work for people ... handle it end to end", "make the safe calls on their own".
    Our product performs that verb: Yes. EventBridge Scheduler -> Lambda pullback-run -> agent/pullback_agent.py build_agent() reads identity, agent/engine/verdict.py decide() rules on it, agent/dispatch.py send_claim() files the claim through SES from a DKIM-verified domain, agent/reply.py classify_reply() drives the manufacturer's answer to a terminal state. The human is touched once per case, at agent/pullback_agent.py approval_gate(), a Strands HumanInTheLoop intervention on the single irreversible tool.
    Metric plan: Notices converted to constraints per run (739 today, every new notice within 24h of publication); cases reaching a terminal state with no human input; false claims held at 0 by the veto. Checked in the console run record and in the DynamoDB run# rows.
    Live by: 2026-09-14. Console live at https://pullback-console.vercel.app, Lambda pullback-run deployed and scheduled daily.
    Deviation from research: Two. The hackathon was found 26 hours before close, so the seven-day live rule was impossible; deploy was made the critical path rather than the last step. And Bedrock plus AgentCore are unavailable because the AWS account is AWS India (AISPL), where they are not offered; Strands is model-agnostic so the agent runs on Anthropic directly while Lambda, EventBridge, DynamoDB, S3 and SES carry the rest.

## The three attacks this has to survive

1. **"This is a notification feed with extra steps."** A feed says a category was
   recalled. Pullback decides whether this purchase falls inside this notice's
   stated constraints, files the claim with the contact printed on the notice,
   and classifies the reply into a terminal state.

2. **"An LLM guessing which of my things is recalled will file false claims."**
   The model never decides. It proposes identity; a deterministic engine rules on
   dates, money and identifiers. A Strands BeforeToolCallEvent hook cancels
   dispatch unless the ledger holds a MATCH and a written claim. Remove the hook
   and the suite goes red by filing a real claim for a product nobody owns.

3. **"Why does this need an agent at all?"** Because 3% of notices carry a UPC
   and 0% carry a model number. Matching a receipt line to a paragraph about
   packaging is reading, done 739 times a year.
