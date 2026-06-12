"""Idempotent seed: hand-translated mirror of frontend/src/data/mockData.ts.

Phase A intentionally hand-translates rather than building a TS→JSON
exporter — the mock data is small, stable, and Phase D replaces it
entirely with live API data. Re-running this script truncates and
re-inserts so it stays safe to call from docker-compose `db-init`.

Usage::

    python -m scripts.seed_from_mock          # inside the container
    docker compose run --rm backend python -m scripts.seed_from_mock
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import delete
from src.models import dashboard as dm
from src.models import domain as dom
from src.models.database import AsyncSessionLocal

# ── Hand-translated mockData ───────────────────────────────────────
TASKS: list[dict[str, Any]] = [
    {
        "id": "t1",
        "title": "Review PR #12 — auto-pr workflow guard",
        "source": "github",
        "due": "Yesterday",
        "priority": "p0",
    },
    {
        "id": "t2",
        "title": "Reply to Sarah re: Q3 launch deck",
        "source": "gmail",
        "due": "Today, 4 pm",
        "priority": "p1",
    },
    {
        "id": "t3",
        "title": 'Draft "AI assistant launch" doc',
        "source": "notion",
        "due": "Tomorrow",
        "priority": "p1",
    },
    {
        "id": "t4",
        "title": "Set up Stripe test account",
        "source": "linear",
        "due": "Wed, 30 Apr",
        "priority": "p2",
    },
    {
        "id": "t5",
        "title": "Onboard new contractor — share repo access",
        "source": "slack",
        "due": "Thu, 1 May",
        "priority": "p2",
    },
    {
        "id": "t6",
        "title": "Renew domain — arshad.ai",
        "source": "gmail",
        "due": "Mon, 5 May",
        "priority": "p3",
    },
]

EVENTS: list[dict[str, Any]] = [
    {
        "id": "e1",
        "title": "Standup — Engineering",
        "start": "10:00 am",
        "duration": "30 min",
        "calendar": "work",
        "source": "Google",
    },
    {
        "id": "e2",
        "title": "1:1 with Priya",
        "start": "2:00 pm",
        "duration": "45 min",
        "calendar": "work",
        "source": "Google",
    },
    {
        "id": "e3",
        "title": "Tennis at Cubbon Park",
        "start": "5:30 pm",
        "duration": "1 hr",
        "calendar": "personal",
        "source": "Apple",
    },
    {
        "id": "e4",
        "title": "Dinner with parents",
        "start": "8:00 pm",
        "duration": "1.5 hr",
        "calendar": "family",
        "source": "Outlook",
    },
]

AGENTS_GLOBAL: list[dict[str, Any]] = [
    {
        "id": "a1",
        "name": "chat-orchestrator",
        "domain": "ai-core",
        "health": "healthy",
        "uptime": "99.8%",
        "accuracy": 94,
        "last_action": "Routed query → calendar agent",
        "last_run": "2 min ago",
    },
    {
        "id": "a2",
        "name": "calendar-ingestor",
        "domain": "data-pipeline",
        "health": "healthy",
        "uptime": "99.2%",
        "accuracy": 98,
        "last_action": "Pulled 4 events from Google",
        "last_run": "14 min ago",
    },
    {
        "id": "a3",
        "name": "email-summarizer",
        "domain": "email",
        "health": "degraded",
        "uptime": "92.4%",
        "accuracy": 86,
        "last_action": "Slow API response (>2 s)",
        "last_run": "1 hr ago",
    },
    {
        "id": "a4",
        "name": "github-ingestor",
        "domain": "data-pipeline",
        "health": "healthy",
        "uptime": "99.6%",
        "accuracy": 96,
        "last_action": "Synced 3 PRs",
        "last_run": "3 hr ago",
    },
    {
        "id": "a5",
        "name": "analytics-processor",
        "domain": "data-pipeline",
        "health": "offline",
        "uptime": "0%",
        "accuracy": 0,
        "last_action": "Failed: connection refused",
        "last_run": "5 hr ago",
    },
]

DAILY_BRIEFING = {
    "id": 1,
    "greeting": "Good afternoon, Arshad",
    "date_label": "Saturday, 25 Apr · 14:42",
    "summary": (
        "You have 3 meetings today, 2 high-priority tasks (one overdue), and "
        "your portfolio is up 1.2%. The email-summarizer agent is running slow "
        "but recoverable. There's 1 decision waiting on you — Sarah's Q3 "
        "launch deck review."
    ),
}

FOCUS_NOW = {
    "id": 1,
    "title": "Reply to Sarah re: Q3 launch deck",
    "subtitle": "Due in 2 h · Gmail · P1",
    "context": (
        "Sarah needs your sign-off on the launch-week comms. Reading time "
        "~6 min, response ~10 min."
    ),
    "action": "Open in Gmail",
}

DECISIONS: list[dict[str, Any]] = [
    {
        "id": "d1",
        "title": "Approve Stripe test mode webhook URL",
        "context": "auth-manager agent escalated — needs human approval",
        "source": "github",
        "waiting_since": "3 h",
    },
    {
        "id": "d2",
        "title": "Confirm dinner attendance — RSVP needed",
        "context": "Calendar invite from Mom",
        "source": "gmail",
        "waiting_since": "1 d",
    },
    {
        "id": "d3",
        "title": "Pick framework for chat streaming (SSE vs WS)",
        "context": "tool-dispatcher needs decision before next sprint",
        "source": "linear",
        "waiting_since": "2 d",
    },
]

AGENT_ACTIVITY: list[dict[str, Any]] = [
    {
        "id": "tk1",
        "agent": "calendar-ingestor",
        "message": "Pulled 4 events from Google",
        "time": "14:28",
    },
    {
        "id": "tk2",
        "agent": "chat-orchestrator",
        "message": "Routed query → events agent",
        "time": "14:25",
    },
    {
        "id": "tk3",
        "agent": "github-ingestor",
        "message": "Synced 3 PR updates",
        "time": "14:20",
    },
    {
        "id": "tk4",
        "agent": "email-summarizer",
        "message": "WARN: API latency 2.3 s",
        "time": "14:14",
    },
    {
        "id": "tk5",
        "agent": "transaction-tagger",
        "message": "Categorized 14 transactions",
        "time": "14:01",
    },
]

HEALTH_HABITS: list[dict[str, Any]] = [
    {"name": "sleep", "value": "7 h 32 m", "delta": "+18 m vs avg"},
    {"name": "steps", "value": "4,820", "delta": "60% of 8 k goal"},
    {"name": "workout", "value": "Tennis", "delta": "scheduled 5:30 pm"},
    {"name": "water", "value": "1.2 / 2.5 L", "delta": "behind by 0.6 L"},
]

NOTIFICATIONS: list[dict[str, Any]] = [
    {
        "id": "n1",
        "severity": "warn",
        "title": "Bill due in 3 days",
        "detail": "Electricity — ₹2,140",
        "time": "12:00",
    },
    {
        "id": "n2",
        "severity": "info",
        "title": "Stock price alert",
        "detail": "NVDA +4.2% today",
        "time": "11:30",
    },
    {
        "id": "n3",
        "severity": "critical",
        "title": "analytics-processor offline",
        "detail": "No retry in 2 hr",
        "time": "09:55",
    },
    {
        "id": "n4",
        "severity": "ok",
        "title": "Backup complete",
        "detail": "Postgres → Supabase",
        "time": "03:00",
    },
]

WEATHER = {"id": 1, "temp": "28 °C", "condition": "Partly cloudy", "city": "Bengaluru"}
COMMUTE = {"id": 1, "eta": "24 min", "mode": "Drive", "dest": "Office (MG Rd)"}

NEWS: list[dict[str, Any]] = [
    {"id": "nw1", "title": "India's GDP grew 7.4% in Q4", "source": "Reuters"},
    {
        "id": "nw2",
        "title": "Anthropic releases Claude 4.7 enterprise",
        "source": "TechCrunch",
    },
]

KNOWLEDGE_SUGGESTIONS: list[str] = [
    "Q3 launch deck — last week's 1:1 notes with Priya",
    "how did we set up the Render deploy?",
    "list all open ADRs for arshad.ai",
]

QUICK_ACTIONS: list[dict[str, Any]] = [
    {"id": "qa1", "label": "Log expense", "hint": "finance"},
    {"id": "qa2", "label": "Add task", "hint": "tasks"},
    {"id": "qa3", "label": "Start meeting notes", "hint": "notion"},
    {"id": "qa4", "label": "Run /gate", "hint": "engineering"},
    {"id": "qa5", "label": "Open chatbot", "hint": "⌘ + K"},
]

# ── Domains ────────────────────────────────────────────────────────
DOMAINS: list[dict[str, Any]] = [
    {
        "slug": "finance",
        "title": "Personal Finance",
        "emoji": "$",
        "tagline": "Net worth · cash flow · investments",
        "kpis": [
            {"label": "Net worth", "value": "₹1.42 Cr", "delta": "+2.1% MoM"},
            {"label": "Monthly spend", "value": "₹68,420", "delta": "−4% vs avg"},
            {"label": "Investment perf", "value": "+1.2%", "delta": "YTD +18%"},
            {"label": "Bills due", "value": "3", "delta": "₹4,820 total"},
        ],
        "applications": [
            {
                "id": "fa1",
                "name": "Expense Logger",
                "description": "Quick-log spend, auto-categorised",
                "status": "live",
            },
            {
                "id": "fa2",
                "name": "Investment Tracker",
                "description": "Holdings across Zerodha + Coinbase",
                "status": "live",
            },
            {
                "id": "fa3",
                "name": "Bill Manager",
                "description": "Recurring bills + auto-pay alerts",
                "status": "beta",
            },
            {
                "id": "fa4",
                "name": "Tax Prep",
                "description": "Auto-aggregates 26AS + Form-16",
                "status": "planned",
            },
        ],
        "agents": [
            {
                "name": "transaction-tagger",
                "description": "Categorises bank transactions",
                "health": "healthy",
                "uptime": "99.5%",
                "accuracy": 92,
                "last_action": "Categorised 14 tx",
                "last_run": "8 min ago",
            },
            {
                "name": "bill-predictor",
                "description": "Forecasts upcoming recurring bills",
                "health": "healthy",
                "uptime": "99.0%",
                "accuracy": 89,
                "last_action": "Predicted 3 bills",
                "last_run": "1 hr ago",
            },
            {
                "name": "investment-researcher",
                "description": "Daily summary of portfolio movement",
                "health": "training",
                "uptime": "94.2%",
                "accuracy": 81,
                "last_action": "Re-training on new data",
                "last_run": "3 hr ago",
            },
        ],
        "feed": [
            {
                "id": "ff1",
                "message": "transaction-tagger categorised ₹4,200 grocery → Food/Home",
                "time": "14:01",
            },
            {
                "id": "ff2",
                "message": "NVDA position +4.2% (₹+8,420 unrealised)",
                "time": "11:30",
            },
            {
                "id": "ff3",
                "message": "Electricity bill prediction: ₹2,140 due 28 Apr",
                "time": "09:00",
            },
        ],
    },
    {
        "slug": "shopify",
        "title": "Shopify Store",
        "emoji": "🛒",
        "tagline": "Orders · inventory · customer ops",
        "kpis": [
            {"label": "Today's orders", "value": "12", "delta": "+25% vs avg day"},
            {"label": "GMV (today)", "value": "₹84,200", "delta": "+18%"},
            {"label": "Low-stock SKUs", "value": "4", "delta": "needs reorder"},
            {"label": "Open tickets", "value": "2", "delta": "avg response 3 h"},
        ],
        "applications": [
            {
                "id": "sa1",
                "name": "Order Triage",
                "description": "Surfaces refund/exchange asks",
                "status": "live",
            },
            {
                "id": "sa2",
                "name": "Inventory Watch",
                "description": "Reorder alerts + supplier mgmt",
                "status": "live",
            },
            {
                "id": "sa3",
                "name": "Customer Reply Drafter",
                "description": "AI drafts for support tickets",
                "status": "beta",
            },
            {
                "id": "sa4",
                "name": "Ad Campaign Optimiser",
                "description": "Meta + Google Ads CPC tuning",
                "status": "planned",
            },
        ],
        "agents": [
            {
                "name": "order-monitor",
                "description": "Watches order stream for anomalies",
                "health": "healthy",
                "uptime": "99.9%",
                "accuracy": 97,
                "last_action": "Flagged 1 high-risk order",
                "last_run": "4 min ago",
            },
            {
                "name": "stock-predictor",
                "description": "Forecasts SKU runout dates",
                "health": "healthy",
                "uptime": "99.1%",
                "accuracy": 90,
                "last_action": "Predicted runout: SKU-441",
                "last_run": "30 min ago",
            },
            {
                "name": "review-summariser",
                "description": "Daily digest of new product reviews",
                "health": "healthy",
                "uptime": "98.7%",
                "accuracy": 88,
                "last_action": "Summarised 7 reviews",
                "last_run": "2 hr ago",
            },
        ],
        "feed": [
            {
                "id": "sf1",
                "message": "Order #4218 flagged: address mismatch with payment country",
                "time": "13:42",
            },
            {
                "id": "sf2",
                "message": "SKU-441 (Steel Bottle) projected runout: 3 days",
                "time": "12:00",
            },
            {
                "id": "sf3",
                "message": 'New review on "Bamboo Cutlery Set" — 5★, "love it"',
                "time": "10:18",
            },
        ],
    },
    {
        "slug": "stocks",
        "title": "Stock Market",
        "emoji": "↗",
        "tagline": "Portfolio · watchlist · research",
        "kpis": [
            {"label": "Portfolio value", "value": "₹52.4 L", "delta": "+1.2% today"},
            {"label": "Day P&L", "value": "+₹62,180", "delta": "best holding NVDA"},
            {"label": "Watchlist alerts", "value": "3", "delta": "2 above target"},
            {"label": "Cash buffer", "value": "₹3.2 L", "delta": "ready to deploy"},
        ],
        "applications": [
            {
                "id": "st1",
                "name": "Live Portfolio",
                "description": "Real-time holdings + P&L",
                "status": "live",
            },
            {
                "id": "st2",
                "name": "Watchlist",
                "description": "Price alerts + technical tags",
                "status": "live",
            },
            {
                "id": "st3",
                "name": "Earnings Calendar",
                "description": "Upcoming earnings for holdings",
                "status": "beta",
            },
            {
                "id": "st4",
                "name": "Options Strategist",
                "description": "Trade-idea generator",
                "status": "planned",
            },
        ],
        "agents": [
            {
                "name": "price-watcher",
                "description": "Polls quotes, fires alerts",
                "health": "healthy",
                "uptime": "99.95%",
                "accuracy": 99,
                "last_action": "NVDA crossed ₹X target",
                "last_run": "1 min ago",
            },
            {
                "name": "earnings-summariser",
                "description": "Day-after earnings digest",
                "health": "healthy",
                "uptime": "98.8%",
                "accuracy": 91,
                "last_action": "Summarised TSLA earnings",
                "last_run": "1 d ago",
            },
            {
                "name": "sentiment-tracker",
                "description": "X / news sentiment per ticker",
                "health": "degraded",
                "uptime": "88.4%",
                "accuracy": 78,
                "last_action": "Twitter rate-limited",
                "last_run": "2 hr ago",
            },
        ],
        "feed": [
            {"id": "stf1", "message": "NVDA crossed ₹X (target hit)", "time": "14:18"},
            {
                "id": "stf2",
                "message": "Watchlist: GOOGL down 1.8% on regulator news",
                "time": "13:00",
            },
            {
                "id": "stf3",
                "message": "Earnings reminder: AAPL reports Wed after-market",
                "time": "09:30",
            },
        ],
    },
    {
        "slug": "health",
        "title": "Health & Fitness",
        "emoji": "💪",
        "tagline": "Sleep · activity · vitals · habits",
        "kpis": [
            {"label": "Sleep (last)", "value": "7 h 32 m", "delta": "+18 m vs avg"},
            {"label": "Steps today", "value": "4,820", "delta": "60% of goal"},
            {"label": "Resting HR", "value": "62 bpm", "delta": "within range"},
            {"label": "Workout streak", "value": "11 days", "delta": "PB: 14 d"},
        ],
        "applications": [
            {
                "id": "ha1",
                "name": "Sleep Log",
                "description": "Last 30 d trends + score",
                "status": "live",
            },
            {
                "id": "ha2",
                "name": "Workout Planner",
                "description": "Auto-plans rest/intensity weeks",
                "status": "beta",
            },
            {
                "id": "ha3",
                "name": "Nutrition Tracker",
                "description": "Macros + meal logging",
                "status": "beta",
            },
            {
                "id": "ha4",
                "name": "Body Composition",
                "description": "Trends from smart scale",
                "status": "planned",
            },
        ],
        "agents": [
            {
                "name": "sleep-coach",
                "description": "Personalised wind-down advice",
                "health": "healthy",
                "uptime": "99.4%",
                "accuracy": 86,
                "last_action": "Suggested 22:30 lights-out",
                "last_run": "6 hr ago",
            },
            {
                "name": "workout-planner",
                "description": "Adjusts plan based on recovery",
                "health": "healthy",
                "uptime": "98.9%",
                "accuracy": 84,
                "last_action": "Swapped HIIT → mobility",
                "last_run": "1 d ago",
            },
            {
                "name": "nutrition-tracker",
                "description": "Reads pantry, suggests meals",
                "health": "training",
                "uptime": "92.1%",
                "accuracy": 73,
                "last_action": "Re-training on new logs",
                "last_run": "2 d ago",
            },
        ],
        "feed": [
            {
                "id": "hf1",
                "message": "Sleep score 84 (good). Deep sleep +12 min vs avg",
                "time": "07:00",
            },
            {
                "id": "hf2",
                "message": "Tennis booked 5:30 pm — 1 hr cardio",
                "time": "11:00",
            },
            {
                "id": "hf3",
                "message": "Water intake 0.6 L behind goal — drink 2 glasses by 3 pm",
                "time": "13:00",
            },
        ],
    },
    {
        "slug": "learning",
        "title": "Learning · Second Brain",
        "emoji": "📚",
        "tagline": "Notes · papers · highlights · knowledge graph",
        "kpis": [
            {"label": "Notes total", "value": "4,218", "delta": "+12 this week"},
            {"label": "Reading queue", "value": "14 items", "delta": "~18 hr to clear"},
            {"label": "Papers read MTD", "value": "7", "delta": "goal: 12"},
            {"label": "Streak", "value": "23 days", "delta": "daily review"},
        ],
        "applications": [
            {
                "id": "la1",
                "name": "Notion Vault",
                "description": "Indexed search + RAG",
                "status": "live",
            },
            {
                "id": "la2",
                "name": "Reading Queue",
                "description": "Pocket / ArXiv / RSS unified",
                "status": "live",
            },
            {
                "id": "la3",
                "name": "Flashcard Generator",
                "description": "Anki-style cards from highlights",
                "status": "beta",
            },
            {
                "id": "la4",
                "name": "Knowledge Graph",
                "description": "Concept-link explorer",
                "status": "planned",
            },
        ],
        "agents": [
            {
                "name": "note-indexer",
                "description": "Embeds + semantically tags new notes",
                "health": "healthy",
                "uptime": "99.6%",
                "accuracy": 95,
                "last_action": "Indexed 12 new notes",
                "last_run": "20 min ago",
            },
            {
                "name": "paper-summariser",
                "description": "TL;DR + claims for ArXiv papers",
                "health": "healthy",
                "uptime": "98.3%",
                "accuracy": 89,
                "last_action": 'Summarised "RAG Survey 2026"',
                "last_run": "4 hr ago",
            },
            {
                "name": "recall-trainer",
                "description": "Spaced-repetition prompts at the right time",
                "health": "healthy",
                "uptime": "99.0%",
                "accuracy": 91,
                "last_action": "Sent 8 recall prompts",
                "last_run": "6 hr ago",
            },
        ],
        "feed": [
            {"id": "lf1", "message": "Indexed 12 new notes (Notion)", "time": "14:20"},
            {
                "id": "lf2",
                "message": 'Paper summary ready: "Retrieval-Augmented Generation Survey 2026"',
                "time": "10:00",
            },
            {
                "id": "lf3",
                "message": "Flashcards generated: 6 from highlights last night",
                "time": "07:30",
            },
        ],
    },
    {
        "slug": "home",
        "title": "Home & IoT",
        "emoji": "🏠",
        "tagline": "Devices · automations · energy",
        "kpis": [
            {"label": "Devices online", "value": "14 / 16", "delta": "2 offline"},
            {"label": "Energy today", "value": "6.4 kWh", "delta": "−12% vs avg"},
            {"label": "Active scenes", "value": "3", "delta": "Evening, Away, Sleep"},
            {"label": "Alerts open", "value": "1", "delta": "fridge door left open"},
        ],
        "applications": [
            {
                "id": "hoa1",
                "name": "Device Map",
                "description": "All sensors + actuators by room",
                "status": "live",
            },
            {
                "id": "hoa2",
                "name": "Automation Rules",
                "description": "If-this-then-that builder",
                "status": "live",
            },
            {
                "id": "hoa3",
                "name": "Energy Monitor",
                "description": "Per-circuit consumption + cost",
                "status": "beta",
            },
            {
                "id": "hoa4",
                "name": "Security Dashboard",
                "description": "Cameras, locks, motion",
                "status": "planned",
            },
        ],
        "agents": [
            {
                "name": "scene-runner",
                "description": "Triggers scenes by time/presence",
                "health": "healthy",
                "uptime": "99.95%",
                "accuracy": 99,
                "last_action": 'Ran "Evening" scene',
                "last_run": "2 hr ago",
            },
            {
                "name": "energy-coach",
                "description": "Suggests load shifts to off-peak",
                "health": "healthy",
                "uptime": "98.2%",
                "accuracy": 87,
                "last_action": "Recommended shift to 22:00",
                "last_run": "4 hr ago",
            },
            {
                "name": "anomaly-watcher",
                "description": "Detects unusual device behaviour",
                "health": "degraded",
                "uptime": "95.0%",
                "accuracy": 82,
                "last_action": "Flagged fridge alert",
                "last_run": "12 min ago",
            },
        ],
        "feed": [
            {"id": "hof1", "message": "Fridge door left open > 5 min", "time": "14:30"},
            {
                "id": "hof2",
                "message": "Evening scene ran — lights 40%, AC 24°C",
                "time": "12:00",
            },
            {
                "id": "hof3",
                "message": "AC unit (bedroom) drawing 18% more than baseline",
                "time": "10:00",
            },
        ],
    },
    {
        "slug": "travel",
        "title": "Travel",
        "emoji": "✈️",
        "tagline": "Trips · bookings · expenses · packing",
        "kpis": [
            {"label": "Upcoming trips", "value": "2", "delta": "next: 12 May"},
            {"label": "Miles balance", "value": "142,300", "delta": "+12k MTD"},
            {"label": "Open bookings", "value": "5", "delta": "flights + hotels"},
            {"label": "Travel spend YTD", "value": "₹4.8 L", "delta": "budget 50%"},
        ],
        "applications": [
            {
                "id": "ta1",
                "name": "Trip Planner",
                "description": "Itinerary + reservations in one view",
                "status": "live",
            },
            {
                "id": "ta2",
                "name": "Booking Tracker",
                "description": "PNRs, hotel bookings, refunds",
                "status": "live",
            },
            {
                "id": "ta3",
                "name": "Packing Lists",
                "description": "Auto-generated by trip type/weather",
                "status": "beta",
            },
            {
                "id": "ta4",
                "name": "Expense Splitter",
                "description": "Family/friends trip cost split",
                "status": "planned",
            },
        ],
        "agents": [
            {
                "name": "fare-watcher",
                "description": "Alerts on price drops for routes",
                "health": "healthy",
                "uptime": "99.4%",
                "accuracy": 93,
                "last_action": "Found ₹2,400 cheaper BLR→GOA",
                "last_run": "1 hr ago",
            },
            {
                "name": "itinerary-builder",
                "description": "Drafts full itineraries from prompts",
                "health": "healthy",
                "uptime": "98.7%",
                "accuracy": 88,
                "last_action": "Drafted 3-day Goa plan",
                "last_run": "3 d ago",
            },
            {
                "name": "visa-tracker",
                "description": "Watches visa requirements + expiry",
                "health": "healthy",
                "uptime": "99.0%",
                "accuracy": 96,
                "last_action": "Checked Schengen rules",
                "last_run": "5 d ago",
            },
        ],
        "feed": [
            {
                "id": "tf1",
                "message": "BLR → GOA fare dropped: ₹4,200 (was ₹6,600)",
                "time": "13:00",
            },
            {
                "id": "tf2",
                "message": "Hotel booking confirmed: Park Hyatt Goa, 12–15 May",
                "time": "10:00",
            },
            {
                "id": "tf3",
                "message": 'Itinerary v2 ready for "Goa weekend"',
                "time": "09:00",
            },
        ],
    },
]

NAV_ITEMS: list[dict[str, Any]] = [
    {"path": "/", "label": "Dashboard", "icon": "▣", "domain": None, "ord": 0},
    {
        "path": "/finance",
        "label": "Personal Finance",
        "icon": "$",
        "domain": "finance",
        "ord": 1,
    },
    {
        "path": "/shopify",
        "label": "Shopify Store",
        "icon": "🛒",
        "domain": "shopify",
        "ord": 2,
    },
    {
        "path": "/stocks",
        "label": "Stock Market",
        "icon": "↗",
        "domain": "stocks",
        "ord": 3,
    },
    {
        "path": "/health",
        "label": "Health & Fitness",
        "icon": "💪",
        "domain": "health",
        "ord": 4,
    },
    {
        "path": "/learning",
        "label": "Learning",
        "icon": "📚",
        "domain": "learning",
        "ord": 5,
    },
    {
        "path": "/home-iot",
        "label": "Home & IoT",
        "icon": "🏠",
        "domain": "home",
        "ord": 6,
    },
    {"path": "/travel", "label": "Travel", "icon": "✈️", "domain": "travel", "ord": 7},
    {
        "path": "/ai-ecosystem",
        "label": "AI Ecosystem",
        "icon": "🤖",
        "domain": None,
        "ord": 8,
    },
]


# ── Agent disk-sync helpers ────────────────────────────────────────

_DEV_TEAM_STAGES: dict[str, int] = {
    "dev-team-orchestrator": 0,
    "code-explorer": 5,
    "business-analyst": 100,
    "enterprise-architect": 200,
    "ai-engineer": 250,
    "solution-architect": 300,
    "architecture-critic": 310,
    "system-engineer": 330,
    "engineer": 350,
    "developer": 400,
    "database-specialist": 415,
    "python-specialist": 416,
    "code-reviewer": 420,
    "frontend-engineer": 430,
    "type-design-analyzer": 440,
    "senior-engineer": 450,
    "software-architect": 460,
    "silent-failure-hunter": 470,
    "code-simplifier": 480,
    "process-organiser": 500,
    "test-architect": 590,
    "test-script-writer": 600,
    "pr-test-analyzer": 610,
    "tester": 700,
    "bug-fixer": 800,
    "debugger": 850,
    "performance-optimisation-engineer": 860,
    "security-auditor": 870,
    "devops-engineer": 880,
    "production-validator": 890,
}

_MODEL_MAP = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
    "fable": "claude-fable-5",
}


def _normalize_model(raw: str) -> str:
    raw = raw.strip().lower()
    if raw in _MODEL_MAP:
        return _MODEL_MAP[raw]
    for key, value in _MODEL_MAP.items():
        if key in raw:
            return value
    if raw in ("inherit", "default", ""):
        return "claude-sonnet-4-6"
    return raw or "claude-sonnet-4-6"


def _parse_frontmatter(path: Path) -> dict[str, str] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    result: dict[str, str] = {}
    for line in block.splitlines():
        m = re.match(r'^(\w[\w-]*):\s*"?([^"]*)"?\s*$', line)
        if m:
            result[m.group(1)] = m.group(2).strip()
    return result or None


def _agent_row(path: Path, is_dev_team: bool) -> dict[str, Any] | None:
    fm = _parse_frontmatter(path)
    if not fm:
        return None
    agent_name = fm.get("name", "").strip()
    if not agent_name:
        return None
    raw_desc = fm.get("description", "").strip()
    purpose = raw_desc[:250] if raw_desc else f"{agent_name} agent"
    display_name = agent_name.replace("-", " ").title()
    model = _normalize_model(fm.get("model", ""))
    category = "development_team" if is_dev_team else "other"
    pipeline_stage = _DEV_TEAM_STAGES.get(agent_name) if is_dev_team else None
    return {
        "agent_name": agent_name,
        "display_name": display_name,
        "purpose": purpose,
        "model": model,
        "category": category,
        "pipeline_stage": pipeline_stage,
        "is_active": True,
    }


async def sync_agents_from_disk(s: Any) -> int:
    """Upsert every agent .md file found on disk into AgentRegistry."""
    scripts_dir = Path(__file__).parent
    backend_dir = scripts_dir.parent
    project_root = backend_dir.parent

    rows: dict[str, dict[str, Any]] = {}

    # 1. backend/src/agents/ — vendored/external agents (all 'other')
    backend_agents = backend_dir / "src" / "agents"
    if backend_agents.is_dir():
        for md in backend_agents.rglob("*.md"):
            row = _agent_row(md, is_dev_team=False)
            if row:
                rows[row["agent_name"]] = row

    # 2. .claude/agents/ non-dev-team — first-party 'other' agents
    claude_agents = project_root / ".claude" / "agents"
    dev_team_dir = claude_agents / "dev-team"
    if claude_agents.is_dir():
        for md in claude_agents.rglob("*.md"):
            if dev_team_dir in md.parents:
                continue  # handled in pass 3
            row = _agent_row(md, is_dev_team=False)
            if row:
                rows[row["agent_name"]] = row

    # 3. .claude/agents/dev-team/ — pipeline agents; always win on name conflict
    if dev_team_dir.is_dir():
        for md in dev_team_dir.glob("*.md"):
            row = _agent_row(md, is_dev_team=True)
            if row:
                rows[row["agent_name"]] = row

    if not rows:
        return 0

    stmt = pg_insert(AgentRegistry).values(list(rows.values()))
    stmt = stmt.on_conflict_do_update(
        index_elements=["agent_name"],
        set_={
            "display_name": stmt.excluded.display_name,
            "purpose": stmt.excluded.purpose,
            "model": stmt.excluded.model,
            "category": stmt.excluded.category,
            "pipeline_stage": stmt.excluded.pipeline_stage,
            "is_active": stmt.excluded.is_active,
        },
    )
    await s.execute(stmt)
    return len(rows)


# ── Seed runner ────────────────────────────────────────────────────
async def seed() -> None:
    async with AsyncSessionLocal() as s:
        # Truncate in reverse-FK order
        for table in (
            dom.DomainFeedRow,
            dom.DomainAgent,
            dom.DomainApplication,
            dom.DomainKPI,
            dom.NavItem,
            dom.Domain,
            dm.Task,
            dm.Event,
            dm.AgentGlobal,
            dm.Decision,
            dm.AgentTick,
            dm.Notification,
            dm.NewsItem,
            dm.KnowledgeSuggestion,
            dm.QuickAction,
            dm.HealthHabit,
            dm.DailyBriefing,
            dm.FocusBlock,
            dm.Weather,
            dm.Commute,
        ):
            await s.execute(delete(table))

        # Dashboard widgets
        s.add_all([dm.Task(**t) for t in TASKS])
        s.add_all([dm.Event(**e) for e in EVENTS])
        s.add_all([dm.AgentGlobal(**a) for a in AGENTS_GLOBAL])
        s.add_all([dm.Decision(**d) for d in DECISIONS])
        s.add_all([dm.AgentTick(**t) for t in AGENT_ACTIVITY])
        s.add_all([dm.Notification(**n) for n in NOTIFICATIONS])
        s.add_all([dm.NewsItem(**n) for n in NEWS])
        s.add_all([dm.KnowledgeSuggestion(text=t) for t in KNOWLEDGE_SUGGESTIONS])
        s.add_all([dm.QuickAction(**q) for q in QUICK_ACTIONS])
        s.add_all([dm.HealthHabit(**h) for h in HEALTH_HABITS])
        s.add(dm.DailyBriefing(**DAILY_BRIEFING))
        s.add(dm.FocusBlock(**FOCUS_NOW))
        s.add(dm.Weather(**WEATHER))
        s.add(dm.Commute(**COMMUTE))

        # Domains + nav
        for d in DOMAINS:
            s.add(
                dom.Domain(
                    slug=d["slug"],
                    title=d["title"],
                    emoji=d["emoji"],
                    tagline=d["tagline"],
                )
            )
            for ord_, kpi in enumerate(d["kpis"]):
                s.add(dom.DomainKPI(domain_slug=d["slug"], ord=ord_, **kpi))
            for app in d["applications"]:
                s.add(dom.DomainApplication(domain_slug=d["slug"], **app))
            for agent in d["agents"]:
                s.add(dom.DomainAgent(domain_slug=d["slug"], **agent))
            for row in d["feed"]:
                s.add(dom.DomainFeedRow(domain_slug=d["slug"], **row))

        s.add_all([dom.NavItem(**n) for n in NAV_ITEMS])

        await s.commit()

        # Sync all agent .md files from disk into AgentRegistry (upsert)
        agent_count = await sync_agents_from_disk(s)
        await s.commit()

        print(
            f"Seed complete: {len(DOMAINS)} domains, {len(TASKS)} tasks, "
            f"{len(EVENTS)} events, {len(NAV_ITEMS)} nav items, "
            f"{agent_count} agents synced."
        )


if __name__ == "__main__":
    asyncio.run(seed())
