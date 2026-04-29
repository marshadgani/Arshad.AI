# Process Hierarchy

This document is the single source of truth for every shipped feature in
Arshad.AI. The Process Organiser agent appends to this file after each
pipeline run; entries are never removed or rewritten in place.

Format:
```
Domain: <Domain Name>
Sub-section: <Sub-section Name>
[FEAT-NNN] <Feature name> — added <ISO timestamp>
```

<!-- Entries appended below this line by Process Organiser. Do not edit by hand. -->

Domain: AI Core
Sub-section: AI plumbing
[FEAT-030] Anthropic SDK Wrapper Service — added 2026-04-26T23:55:00+00:00

Sub-section: Tools
[FEAT-047] Generic Tool Run Endpoint — added 2026-04-26T23:55:00+00:00
[FEAT-048] OAuth Token Service (auto-refresh) — added 2026-04-26T23:55:00+00:00

Sub-section: Orchestration
[FEAT-061] Chat Orchestrator Agent — added 2026-04-26T23:55:00+00:00
[FEAT-062] Tool Dispatcher Agent — added 2026-04-26T23:55:00+00:00
[FEAT-063] Context Manager Agent — added 2026-04-26T23:55:00+00:00
[FEAT-064] Response Streamer Agent — added 2026-04-26T23:55:00+00:00

Sub-section: Specialty
[FEAT-065] Council Chairman (multi-model panel) — added 2026-04-26T23:55:00+00:00

Sub-section: Discovery
[FEAT-077] List Agents Endpoint — added 2026-04-26T23:55:00+00:00
[FEAT-078] Generic Agent Run Endpoint — added 2026-04-26T23:55:00+00:00


Domain: Auth
Sub-section: Sign-in flow
[FEAT-001] Google OAuth Login — added 2026-04-26T23:55:00+00:00
[FEAT-002] GitHub OAuth Login — added 2026-04-26T23:55:00+00:00

Sub-section: Session
[FEAT-003] Current User Profile — added 2026-04-26T23:55:00+00:00
[FEAT-004] Logout — added 2026-04-26T23:55:00+00:00
[FEAT-005] JWT Token Encoding/Decoding — added 2026-04-26T23:55:00+00:00

Sub-section: Token vault
[FEAT-006] OAuth Provider Token Storage (encrypted) — added 2026-04-26T23:55:00+00:00

Sub-section: Frontend
[FEAT-114] Frontend Auth Callback Page — added 2026-04-26T23:55:00+00:00
[FEAT-115] Frontend Login Page — added 2026-04-26T23:55:00+00:00


Domain: Calendar
Sub-section: Tools
[FEAT-033] Calendar.create_event Tool — added 2026-04-26T23:55:00+00:00
[FEAT-034] Calendar.update_event Tool — added 2026-04-26T23:55:00+00:00
[FEAT-035] Calendar.list_events Tool — added 2026-04-26T23:55:00+00:00
[FEAT-036] Calendar.find_free_slots Tool — added 2026-04-26T23:55:00+00:00

Sub-section: Agents
[FEAT-049] Calendar Event Creator Agent — added 2026-04-26T23:55:00+00:00
[FEAT-050] Calendar Event Updater Agent — added 2026-04-26T23:55:00+00:00
[FEAT-051] Meeting Suggester Agent — added 2026-04-26T23:55:00+00:00
[FEAT-052] Schedule Analyzer Agent — added 2026-04-26T23:55:00+00:00


Domain: Chat
Sub-section: Sessions
[FEAT-024] Create Chat Session — added 2026-04-26T23:55:00+00:00
[FEAT-025] List Chat Sessions — added 2026-04-26T23:55:00+00:00
[FEAT-027] Delete Chat Session — added 2026-04-26T23:55:00+00:00

Sub-section: Messages
[FEAT-026] Get Session Message History — added 2026-04-26T23:55:00+00:00
[FEAT-028] Send Message via SSE Streaming — added 2026-04-26T23:55:00+00:00

Sub-section: Routing
[FEAT-029] Two-Stage Intent Classification — added 2026-04-26T23:55:00+00:00
[FEAT-032] Chat Tool Subset Resolution — added 2026-04-26T23:55:00+00:00

Sub-section: Context
[FEAT-031] Conversation History Token Compression — added 2026-04-26T23:55:00+00:00

Sub-section: Frontend
[FEAT-116] Frontend Chat UI — added 2026-04-26T23:55:00+00:00


Domain: Code
Sub-section: Tools
[FEAT-041] GitHub.create_issue Tool — added 2026-04-26T23:55:00+00:00
[FEAT-042] GitHub.update_issue Tool — added 2026-04-26T23:55:00+00:00
[FEAT-043] GitHub.list_issues Tool — added 2026-04-26T23:55:00+00:00
[FEAT-044] GitHub.list_prs Tool — added 2026-04-26T23:55:00+00:00
[FEAT-045] GitHub.get_pr Tool — added 2026-04-26T23:55:00+00:00
[FEAT-046] GitHub.get_commit Tool — added 2026-04-26T23:55:00+00:00

Sub-section: Agents
[FEAT-057] Issue Manager Agent — added 2026-04-26T23:55:00+00:00
[FEAT-058] PR Reviewer Agent — added 2026-04-26T23:55:00+00:00
[FEAT-059] Code Summarizer Agent — added 2026-04-26T23:55:00+00:00
[FEAT-060] Repo Monitor Agent — added 2026-04-26T23:55:00+00:00


Domain: Communication
Sub-section: Tools
[FEAT-037] Gmail.search_threads Tool — added 2026-04-26T23:55:00+00:00
[FEAT-038] Gmail.get_thread Tool — added 2026-04-26T23:55:00+00:00
[FEAT-039] Gmail.create_draft Tool — added 2026-04-26T23:55:00+00:00
[FEAT-040] Gmail.apply_label Tool — added 2026-04-26T23:55:00+00:00

Sub-section: Agents
[FEAT-053] Email Searcher Agent — added 2026-04-26T23:55:00+00:00
[FEAT-054] Email Drafter Agent — added 2026-04-26T23:55:00+00:00
[FEAT-055] Email Labeler Agent — added 2026-04-26T23:55:00+00:00
[FEAT-056] Email Summarizer Agent — added 2026-04-26T23:55:00+00:00

Sub-section: Personal OAuth
[FEAT-103] Discord (personal integration) — added 2026-04-26T23:55:00+00:00


Domain: Dashboard
Sub-section: Singletons
[FEAT-007] Daily Briefing Widget — added 2026-04-26T23:55:00+00:00
[FEAT-008] Current Focus Block Widget — added 2026-04-26T23:55:00+00:00
[FEAT-009] Weather Widget — added 2026-04-26T23:55:00+00:00
[FEAT-010] Commute Widget — added 2026-04-26T23:55:00+00:00

Sub-section: Collections
[FEAT-011] Tasks List Widget — added 2026-04-26T23:55:00+00:00
[FEAT-012] Events List Widget (with ingestion fallback) — added 2026-04-26T23:55:00+00:00
[FEAT-013] Cross-Domain Agents Roster — added 2026-04-26T23:55:00+00:00
[FEAT-014] Decisions Awaiting User — added 2026-04-26T23:55:00+00:00
[FEAT-015] Live Agent Activity Ticker — added 2026-04-26T23:55:00+00:00
[FEAT-016] Notifications Widget — added 2026-04-26T23:55:00+00:00
[FEAT-017] News Headlines Widget — added 2026-04-26T23:55:00+00:00
[FEAT-018] Quick Actions Widget — added 2026-04-26T23:55:00+00:00
[FEAT-019] Health & Habits Widget — added 2026-04-26T23:55:00+00:00
[FEAT-020] Knowledge Suggestions Widget — added 2026-04-26T23:55:00+00:00

Sub-section: Domain catalogue
[FEAT-021] Domain List Endpoint — added 2026-04-26T23:55:00+00:00
[FEAT-022] Single Domain Configuration — added 2026-04-26T23:55:00+00:00

Sub-section: Navigation
[FEAT-023] Sidebar Nav Items — added 2026-04-26T23:55:00+00:00


Domain: Data Pipeline
Sub-section: Ingestion
[FEAT-066] Calendar Ingestor Agent — added 2026-04-26T23:55:00+00:00
[FEAT-067] Email Ingestor Agent — added 2026-04-26T23:55:00+00:00
[FEAT-068] GitHub Ingestor Agent — added 2026-04-26T23:55:00+00:00

Sub-section: Aggregation
[FEAT-069] Analytics Processor Agent — added 2026-04-26T23:55:00+00:00

Sub-section: Runtime
[FEAT-070] In-Process Queue Worker — added 2026-04-26T23:55:00+00:00
[FEAT-071] List Ingestion Runs — added 2026-04-26T23:55:00+00:00
[FEAT-072] Get Ingestion Run by ID — added 2026-04-26T23:55:00+00:00


Domain: Finance
Sub-section: Personal OAuth
[FEAT-093] Plaid (personal integration) — added 2026-04-26T23:55:00+00:00
[FEAT-102] Coinbase (personal integration) — added 2026-04-26T23:55:00+00:00

Sub-section: Personal API-key
[FEAT-096] Zerodha Kite (personal integration) — added 2026-04-26T23:55:00+00:00
[FEAT-097] Upstox (personal integration) — added 2026-04-26T23:55:00+00:00


Domain: Health
Sub-section: Personal OAuth
[FEAT-099] Strava (personal integration) — added 2026-04-26T23:55:00+00:00
[FEAT-100] Oura Ring (personal integration) — added 2026-04-26T23:55:00+00:00
[FEAT-101] Fitbit (personal integration) — added 2026-04-26T23:55:00+00:00


Domain: Infrastructure
Sub-section: Cross-cutting
[FEAT-073] API Gateway Agent — added 2026-04-26T23:55:00+00:00
[FEAT-074] Auth Manager Agent — added 2026-04-26T23:55:00+00:00
[FEAT-075] Cache Manager Agent — added 2026-04-26T23:55:00+00:00
[FEAT-076] Health Monitor Agent — added 2026-04-26T23:55:00+00:00

Sub-section: Health
[FEAT-079] Liveness Probe — added 2026-04-26T23:55:00+00:00

Sub-section: Errors
[FEAT-080] Global Error Envelope Handler — added 2026-04-26T23:55:00+00:00

Sub-section: Project
[FEAT-109] Render (project integration) — added 2026-04-26T23:55:00+00:00
[FEAT-110] Supabase (project integration) — added 2026-04-26T23:55:00+00:00
[FEAT-111] Vercel (project integration) — added 2026-04-26T23:55:00+00:00


Domain: Integrations
Sub-section: Catalogue
[FEAT-081] List Integrations + Per-User Status — added 2026-04-26T23:55:00+00:00

Sub-section: Lifecycle
[FEAT-082] Connect Integration — added 2026-04-26T23:55:00+00:00
[FEAT-083] Sync Integration — added 2026-04-26T23:55:00+00:00
[FEAT-084] Disconnect Integration — added 2026-04-26T23:55:00+00:00
[FEAT-085] Integration Status Endpoint — added 2026-04-26T23:55:00+00:00

Sub-section: OAuth
[FEAT-086] Generic OAuth Callback — added 2026-04-26T23:55:00+00:00

Sub-section: Personal OAuth
[FEAT-087] Google Calendar (personal integration) — added 2026-04-26T23:55:00+00:00
[FEAT-088] Gmail (personal integration) — added 2026-04-26T23:55:00+00:00
[FEAT-089] Google Drive (personal integration) — added 2026-04-26T23:55:00+00:00
[FEAT-090] Google Tasks (personal integration) — added 2026-04-26T23:55:00+00:00
[FEAT-091] YouTube (personal integration) — added 2026-04-26T23:55:00+00:00
[FEAT-092] GitHub (personal integration) — added 2026-04-26T23:55:00+00:00
[FEAT-098] Spotify (personal integration) — added 2026-04-26T23:55:00+00:00

Sub-section: Personal API-key
[FEAT-094] OpenWeatherMap (personal integration) — added 2026-04-26T23:55:00+00:00
[FEAT-095] Stack Overflow (personal integration) — added 2026-04-26T23:55:00+00:00

Sub-section: Project
[FEAT-108] Google Maps (project integration) — added 2026-04-26T23:55:00+00:00

Sub-section: Project bulk
[FEAT-112] Bulk Project API-Key Providers (Upstash/Cloudflare/Stripe/Sentry/Anthropic/OpenAI/Notion/Slack/Todoist/News API) — added 2026-04-26T23:55:00+00:00

Sub-section: Roadmap
[FEAT-113] Coming-Soon Provider Stubs — added 2026-04-26T23:55:00+00:00

Sub-section: Frontend
[FEAT-117] Integrations Frontend Page — added 2026-04-26T23:55:00+00:00


Domain: Lifestyle
Sub-section: Personal OAuth
[FEAT-104] Reddit (personal integration) — added 2026-04-26T23:55:00+00:00

Sub-section: Static
[FEAT-106] Hacker News (static integration) — added 2026-04-26T23:55:00+00:00
[FEAT-107] Open-Meteo (static integration) — added 2026-04-26T23:55:00+00:00


Domain: Productivity
Sub-section: Personal OAuth
[FEAT-105] Linear (personal integration, GraphQL) — added 2026-04-26T23:55:00+00:00


