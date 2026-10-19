# AI research copilot (Milestone 6)

`/ai-research` (web) · `POST /api/v1/research/query` (API) · code in `apps/api/app/ai/`.

## What it is
A tool-calling assistant (Anthropic Messages API, model `claude-opus-5-5` by default) that answers research questions
**only** from the platform's own typed tools. It has no internet access and no other data. It never executes orders
and gives no investment advice.

## Flow
1. The question (and up to 5 earlier questions/answers from the same user thread) goes to the model with a cached
   system prompt and 13 strict tool schemas.
2. The model calls tools; each call is validated (Pydantic), executed against the database, and stored as an
   evidence item `E1, E2, …` with inputs, data, sources, `as_of`, quality and a fixture flag. Invalid input returns
   an `is_error` tool result (`INVALID_INPUT: …`); the model may correct itself.
3. The loop runs at most `ATLAS_AI_MAX_ROUNDS` (8) rounds; the last round disables tools (`tool_choice: none`) so an
   answer is always produced from the evidence gathered.
4. The final answer must cite `[E#]` after every figure. A **deterministic verifier** (`app/ai/verify.py`, no model)
   then extracts every numeric claim and checks it against the cited evidence:

| Claim status | Meaning |
|---|---|
| `verified` | The value (after unit/percent/magnitude normalisation, rounding tolerance) appears in a cited evidence item |
| `mismatch` | It cites evidence, but the value is not in it |
| `uncited` | No citation, but the value exists in some evidence item |
| `unsupported` | No evidence item contains the value (e.g. a forecast) |

Citations to non-existent evidence ids are reported separately. Dates, years and small bare integers are not treated
as claims. The overall status is `verified`, `partially_verified`, `unverified_claims` or `no_numeric_claims` and is
shown as a badge; every flagged figure is listed under the answer.

## Tools
`search_instruments`, `get_equity_snapshot`, `get_technical_indicators`, `calculate_risk_metrics`,
`get_fund_profile`, `compare_funds`, `rank_funds`, `screen_instruments`, `get_portfolio_analytics` (the signed-in
user's own portfolios only). `get_financial_statements`, `get_valuation_metrics`, `get_macro_series` and
`get_disclosures` exist but return `UNAVAILABLE` (no licensed source); the model is told to say so.

## Safety controls
- Tool results are wrapped as data; the system prompt tells the model that instructions inside them are not to be followed.
- Fixture data carries a `FIXTURE` warning into every tool result; the model must disclose it.
- Sign-in required; per-user limit `ATLAS_AI_QUERIES_PER_MIN` (6/min); every query, its evidence and verification are
  stored (`research_queries`) and audited (`research.query`).
- Model refusals are shown as such (`stop_reason = refusal`), never as an empty answer.
- Server-side model fallbacks are enabled (`fallbacks: "default"`); the model that actually answered is stored as `served_by`.

## Configuration
| Variable | Default |
|---|---|
| `ANTHROPIC_API_KEY` | — (required; or an `ant auth login` profile on the API host) |
| `ATLAS_AI_ENABLED` | `true` |
| `ATLAS_AI_MODEL` | `claude-opus-5-5` |
| `ATLAS_AI_EFFORT` | `medium` |
| `ATLAS_AI_MAX_ROUNDS` | `8` |
| `ATLAS_AI_QUERIES_PER_MIN` | `6` |

Without credentials, `/research/status` reports `configured: false` and the page shows setup instructions.

## Limits
- Tested with a scripted fake client (orchestration, request shape, verifier, HTTP layer). Not yet run against the
  live API on this machine (no key).
- The verifier checks that a figure is *present* in the cited evidence, not that the sentence interprets it correctly.
