# Arshad.AI Autonomous Backlog

Tasks here are executed automatically by `.github/workflows/autonomous-backlog.yml`
every 2 hours. Tasks marked `requires_human: yes` are skipped until Arshad reviews them.

Add tasks with: `python scripts/backlog_add.py --title "..." --description "..." --autonomous yes`

---

<!--
TASK FORMAT (copy-paste template):

### TASK-NNN
- status: pending
- requires_human: no
- title: Short title
- added: YYYY-MM-DD
- description: Full description of what to do. Be specific about files, behaviour, acceptance criteria.
- context: relevant/files/or/dirs (space-separated)
-->

### TASK-001
- status: pending
- requires_human: yes
- title: Label or source the finance KPIs on /finance
- added: 2026-09-14
- description: Net worth, Monthly spend, Investment perf, and Bills due on the
  finance DomainPage (frontend/src/pages/PersonalFinance.tsx) are seeded
  fabricated values from backend/scripts/seed_from_mock.py, not derived from
  real transactions. They now sit directly above FundFlowMap, which was just
  labelled "Manual" (FEAT-FUND-FLOW-001) to disclose it is a hand-maintained,
  non-live diagram. By contrast, the unlabelled KPIs above it now read as
  live data even though they are not. Decide whether to label the KPIs as
  illustrative/seeded, wire them to a real data source (e.g. Plaid), or
  remove them. This is a product/UX decision touching the shared DomainPage
  component used by all 7 domains, so it requires human sign-off rather than
  autonomous execution.
- context: frontend/src/components/DomainPage.tsx frontend/src/pages/PersonalFinance.tsx backend/scripts/seed_from_mock.py backend/src/api/v1/domains.py

### TASK-002
- status: pending
- requires_human: yes
- title: SEC-001: personal financial map + family names ship in a public, unauthenticated JS bundle
- added: 2026-09-14
- description: frontend/src/components/FundFlowMap/fundFlowDiagram.ts hardcodes Arshad's real fund-flow topology (Al Rajhi / STC / Amex Saudi accounts, Ersal exchange, ICICI/IOB NRE+NRO, IDBI/SBI/BOB savings, ICICI Coral/Rubyx and SBI Lifestyle credit cards, HDFC home loan, ICICI Term Life / Prudential / Bajaj Alliance policies, employer KaarTech, and named family members incl. 'Jerina - Mother', son and spouse). Vite code-splits it into dist/assets/PersonalFinance-*.js, whose filename is listed in the entry chunk dist/assets/index-*.js. Vercel serves both without auth - ProtectedRoutes in frontend/src/App.tsx is client-side only and does not gate static assets. Anyone can GET / -> read the entry chunk -> GET the PersonalFinance chunk and recover the whole financial + family profile. Decide one of: (a) move the diagram behind an authenticated backend endpoint (GET /api/v1/finance/fund-flow) and render it as JSX from the response, (b) replace institution and person names with generic labels ('Bank A', 'Family member') in the committed SVG, or (c) accept the exposure explicitly. Also purge the data from git history and from any already-deployed Vercel build if (a) or (b) is chosen. Security-sensitive and architectural - needs Arshad's decision.
- context: frontend/src/components/FundFlowMap/fundFlowDiagram.ts frontend/src/components/FundFlowMap/FundFlowMap.tsx frontend/src/App.tsx frontend/vercel.json

