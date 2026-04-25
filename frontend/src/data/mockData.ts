// Mock data for the Arshad.AI dashboard. Each block is shaped to match
// the eventual real-data contract from its integration source, so tiles
// can swap from mock → live without changing component props.

export type Source = 'github' | 'gmail' | 'notion' | 'linear' | 'slack' | 'calendar';
export type Severity = 'critical' | 'warn' | 'info' | 'ok';
export type AgentHealth = 'healthy' | 'training' | 'degraded' | 'offline';
export type CalendarTag = 'work' | 'personal' | 'family' | 'health';

// ── Tasks (auto-prioritised across sources) ────────────────────────
export interface Task {
  id: string;
  title: string;
  source: Source;
  due: string;
  priority: 'p0' | 'p1' | 'p2' | 'p3';
}
export const tasks: Task[] = [
  { id: 't1', title: 'Review PR #12 — auto-pr workflow guard', source: 'github', due: 'Yesterday', priority: 'p0' },
  { id: 't2', title: 'Reply to Sarah re: Q3 launch deck',     source: 'gmail',  due: 'Today, 4 pm', priority: 'p1' },
  { id: 't3', title: 'Draft "AI assistant launch" doc',        source: 'notion', due: 'Tomorrow', priority: 'p1' },
  { id: 't4', title: 'Set up Stripe test account',             source: 'linear', due: 'Wed, 30 Apr', priority: 'p2' },
  { id: 't5', title: 'Onboard new contractor — share repo access', source: 'slack', due: 'Thu, 1 May', priority: 'p2' },
  { id: 't6', title: 'Renew domain — arshad.ai',                source: 'gmail', due: 'Mon, 5 May', priority: 'p3' },
];

// ── Events (multi-calendar synced) ─────────────────────────────────
export interface Event {
  id: string;
  title: string;
  start: string;
  duration: string;
  calendar: CalendarTag;
  source: 'Google' | 'Apple' | 'Outlook';
}
export const events: Event[] = [
  { id: 'e1', title: 'Standup — Engineering',  start: '10:00 am', duration: '30 min', calendar: 'work',     source: 'Google' },
  { id: 'e2', title: '1:1 with Priya',          start: '2:00 pm',  duration: '45 min', calendar: 'work',     source: 'Google' },
  { id: 'e3', title: 'Tennis at Cubbon Park',   start: '5:30 pm',  duration: '1 hr',   calendar: 'personal', source: 'Apple' },
  { id: 'e4', title: 'Dinner with parents',     start: '8:00 pm',  duration: '1.5 hr', calendar: 'family',   source: 'Outlook' },
];

// ── Agents (across all domains) ────────────────────────────────────
export interface Agent {
  id: string;
  name: string;
  domain: string;
  health: AgentHealth;
  uptime: string;
  accuracy: number;
  lastAction: string;
  lastRun: string;
}
export const agents: Agent[] = [
  { id: 'a1', name: 'chat-orchestrator',   domain: 'ai-core',       health: 'healthy',  uptime: '99.8%', accuracy: 94, lastAction: 'Routed query → calendar agent', lastRun: '2 min ago' },
  { id: 'a2', name: 'calendar-ingestor',   domain: 'data-pipeline', health: 'healthy',  uptime: '99.2%', accuracy: 98, lastAction: 'Pulled 4 events from Google',     lastRun: '14 min ago' },
  { id: 'a3', name: 'email-summarizer',    domain: 'email',         health: 'degraded', uptime: '92.4%', accuracy: 86, lastAction: 'Slow API response (>2 s)',         lastRun: '1 hr ago' },
  { id: 'a4', name: 'github-ingestor',     domain: 'data-pipeline', health: 'healthy',  uptime: '99.6%', accuracy: 96, lastAction: 'Synced 3 PRs',                    lastRun: '3 hr ago' },
  { id: 'a5', name: 'analytics-processor', domain: 'data-pipeline', health: 'offline',  uptime: '0%',    accuracy: 0,  lastAction: 'Failed: connection refused',      lastRun: '5 hr ago' },
];

// ── Daily Briefing ─────────────────────────────────────────────────
export const dailyBriefing = {
  greeting: 'Good afternoon, Arshad',
  date: 'Saturday, 25 Apr · 14:42',
  summary:
    "You have 3 meetings today, 2 high-priority tasks (one overdue), and your portfolio is up 1.2%. The email-summarizer agent is running slow but recoverable. There's 1 decision waiting on you — Sarah's Q3 launch deck review.",
};

// ── Focus Now ──────────────────────────────────────────────────────
export const focusNow = {
  title: 'Reply to Sarah re: Q3 launch deck',
  subtitle: 'Due in 2 h · Gmail · P1',
  context:
    'Sarah needs your sign-off on the launch-week comms. Reading time ~6 min, response ~10 min.',
  action: 'Open in Gmail',
};

// ── Decision Queue ─────────────────────────────────────────────────
export interface Decision {
  id: string;
  title: string;
  context: string;
  source: Source;
  waitingSince: string;
}
export const decisions: Decision[] = [
  { id: 'd1', title: 'Approve Stripe test mode webhook URL', context: 'auth-manager agent escalated — needs human approval', source: 'github', waitingSince: '3 h' },
  { id: 'd2', title: 'Confirm dinner attendance — RSVP needed', context: 'Calendar invite from Mom', source: 'gmail', waitingSince: '1 d' },
  { id: 'd3', title: 'Pick framework for chat streaming (SSE vs WS)', context: 'tool-dispatcher needs decision before next sprint', source: 'linear', waitingSince: '2 d' },
];

// ── Agent Activity (live ticker) ───────────────────────────────────
export interface AgentTick {
  id: string;
  agent: string;
  message: string;
  time: string;
}
export const agentActivity: AgentTick[] = [
  { id: 'tk1', agent: 'calendar-ingestor', message: 'Pulled 4 events from Google',           time: '14:28' },
  { id: 'tk2', agent: 'chat-orchestrator', message: 'Routed query → events agent',           time: '14:25' },
  { id: 'tk3', agent: 'github-ingestor',   message: 'Synced 3 PR updates',                   time: '14:20' },
  { id: 'tk4', agent: 'email-summarizer',  message: 'WARN: API latency 2.3 s',                time: '14:14' },
  { id: 'tk5', agent: 'transaction-tagger', message: 'Categorized 14 transactions',           time: '14:01' },
];

// ── Health & Habits ────────────────────────────────────────────────
export const healthHabits = {
  sleep:    { value: '7 h 32 m', delta: '+18 m vs avg' },
  steps:    { value: '4,820',    delta: '60% of 8 k goal' },
  workout:  { value: 'Tennis',   delta: 'scheduled 5:30 pm' },
  water:    { value: '1.2 / 2.5 L', delta: 'behind by 0.6 L' },
};

// ── Notifications ──────────────────────────────────────────────────
export interface Notification {
  id: string;
  severity: Severity;
  title: string;
  detail: string;
  time: string;
}
export const notifications: Notification[] = [
  { id: 'n1', severity: 'warn',     title: 'Bill due in 3 days',        detail: 'Electricity — ₹2,140',    time: '12:00' },
  { id: 'n2', severity: 'info',     title: 'Stock price alert',         detail: 'NVDA +4.2% today',         time: '11:30' },
  { id: 'n3', severity: 'critical', title: 'analytics-processor offline', detail: 'No retry in 2 hr',       time: '09:55' },
  { id: 'n4', severity: 'ok',       title: 'Backup complete',           detail: 'Postgres → Supabase',     time: '03:00' },
];

// ── Weather + Commute + News ───────────────────────────────────────
export const weather = { temp: '28 °C', condition: 'Partly cloudy', city: 'Bengaluru' };
export const commute = { eta: '24 min', mode: 'Drive', dest: 'Office (MG Rd)' };
export const news = [
  { id: 'nw1', title: 'India\'s GDP grew 7.4% in Q4',           source: 'Reuters' },
  { id: 'nw2', title: 'Anthropic releases Claude 4.7 enterprise', source: 'TechCrunch' },
];

// ── Knowledge Search (suggestions) ─────────────────────────────────
export const knowledgeSuggestions = [
  'Q3 launch decklast week\'s 1:1 notes with Priya',
  'how did we set up the Render deploy?',
  'list all open ADRs for arshad.ai',
];

// ── Quick Actions ──────────────────────────────────────────────────
export interface QuickAction {
  id: string;
  label: string;
  hint?: string;
}
export const quickActions: QuickAction[] = [
  { id: 'qa1', label: 'Log expense',          hint: 'finance' },
  { id: 'qa2', label: 'Add task',             hint: 'tasks' },
  { id: 'qa3', label: 'Start meeting notes',  hint: 'notion' },
  { id: 'qa4', label: 'Run /gate',            hint: 'engineering' },
  { id: 'qa5', label: 'Open chatbot',         hint: '⌘ + K' },
];

// ── Domain catalogue ───────────────────────────────────────────────
// Each domain uses the same Application + Agent shape so the
// DomainPage template can render them uniformly.
export interface Application {
  id: string;
  name: string;
  description: string;
  status: 'live' | 'beta' | 'planned';
}
export interface DomainKPI { label: string; value: string; delta?: string; }
export interface DomainAgent {
  name: string;
  description: string;
  health: AgentHealth;
  uptime: string;
  accuracy: number;
  lastAction: string;
  lastRun: string;
}
export interface DomainConfig {
  slug: string;
  title: string;
  emoji: string;
  tagline: string;
  kpis: DomainKPI[];
  applications: Application[];
  agents: DomainAgent[];
  feed: { id: string; message: string; time: string }[];
}

export const domains: Record<string, DomainConfig> = {
  finance: {
    slug: 'finance',
    title: 'Personal Finance',
    emoji: '$',
    tagline: 'Net worth · cash flow · investments',
    kpis: [
      { label: 'Net worth',     value: '₹1.42 Cr', delta: '+2.1% MoM' },
      { label: 'Monthly spend', value: '₹68,420',  delta: '−4% vs avg' },
      { label: 'Investment perf', value: '+1.2%',  delta: 'YTD +18%' },
      { label: 'Bills due',     value: '3',        delta: '₹4,820 total' },
    ],
    applications: [
      { id: 'fa1', name: 'Expense Logger',     description: 'Quick-log spend, auto-categorised', status: 'live' },
      { id: 'fa2', name: 'Investment Tracker', description: 'Holdings across Zerodha + Coinbase', status: 'live' },
      { id: 'fa3', name: 'Bill Manager',       description: 'Recurring bills + auto-pay alerts', status: 'beta' },
      { id: 'fa4', name: 'Tax Prep',           description: 'Auto-aggregates 26AS + Form-16',    status: 'planned' },
    ],
    agents: [
      { name: 'transaction-tagger',  description: 'Categorises bank transactions',          health: 'healthy',  uptime: '99.5%', accuracy: 92, lastAction: 'Categorised 14 tx',         lastRun: '8 min ago' },
      { name: 'bill-predictor',      description: 'Forecasts upcoming recurring bills',      health: 'healthy',  uptime: '99.0%', accuracy: 89, lastAction: 'Predicted 3 bills',          lastRun: '1 hr ago' },
      { name: 'investment-researcher', description: 'Daily summary of portfolio movement',  health: 'training', uptime: '94.2%', accuracy: 81, lastAction: 'Re-training on new data',     lastRun: '3 hr ago' },
    ],
    feed: [
      { id: 'ff1', message: 'transaction-tagger categorised ₹4,200 grocery → Food/Home', time: '14:01' },
      { id: 'ff2', message: 'NVDA position +4.2% (₹+8,420 unrealised)',                   time: '11:30' },
      { id: 'ff3', message: 'Electricity bill prediction: ₹2,140 due 28 Apr',              time: '09:00' },
    ],
  },

  shopify: {
    slug: 'shopify',
    title: 'Shopify Store',
    emoji: '🛒',
    tagline: 'Orders · inventory · customer ops',
    kpis: [
      { label: 'Today\'s orders', value: '12',     delta: '+25% vs avg day' },
      { label: 'GMV (today)',   value: '₹84,200', delta: '+18%' },
      { label: 'Low-stock SKUs', value: '4',     delta: 'needs reorder' },
      { label: 'Open tickets',  value: '2',       delta: 'avg response 3 h' },
    ],
    applications: [
      { id: 'sa1', name: 'Order Triage',          description: 'Surfaces refund/exchange asks',  status: 'live' },
      { id: 'sa2', name: 'Inventory Watch',       description: 'Reorder alerts + supplier mgmt',  status: 'live' },
      { id: 'sa3', name: 'Customer Reply Drafter', description: 'AI drafts for support tickets', status: 'beta' },
      { id: 'sa4', name: 'Ad Campaign Optimiser',  description: 'Meta + Google Ads CPC tuning', status: 'planned' },
    ],
    agents: [
      { name: 'order-monitor',     description: 'Watches order stream for anomalies',     health: 'healthy', uptime: '99.9%', accuracy: 97, lastAction: 'Flagged 1 high-risk order',  lastRun: '4 min ago' },
      { name: 'stock-predictor',   description: 'Forecasts SKU runout dates',             health: 'healthy', uptime: '99.1%', accuracy: 90, lastAction: 'Predicted runout: SKU-441',    lastRun: '30 min ago' },
      { name: 'review-summariser', description: 'Daily digest of new product reviews',     health: 'healthy', uptime: '98.7%', accuracy: 88, lastAction: 'Summarised 7 reviews',         lastRun: '2 hr ago' },
    ],
    feed: [
      { id: 'sf1', message: 'Order #4218 flagged: address mismatch with payment country', time: '13:42' },
      { id: 'sf2', message: 'SKU-441 (Steel Bottle) projected runout: 3 days',             time: '12:00' },
      { id: 'sf3', message: 'New review on "Bamboo Cutlery Set" — 5★, "love it"',          time: '10:18' },
    ],
  },

  stocks: {
    slug: 'stocks',
    title: 'Stock Market',
    emoji: '↗',
    tagline: 'Portfolio · watchlist · research',
    kpis: [
      { label: 'Portfolio value', value: '₹52.4 L', delta: '+1.2% today' },
      { label: 'Day P&L',         value: '+₹62,180', delta: 'best holding NVDA' },
      { label: 'Watchlist alerts', value: '3',      delta: '2 above target' },
      { label: 'Cash buffer',     value: '₹3.2 L',  delta: 'ready to deploy' },
    ],
    applications: [
      { id: 'st1', name: 'Live Portfolio',     description: 'Real-time holdings + P&L',       status: 'live' },
      { id: 'st2', name: 'Watchlist',          description: 'Price alerts + technical tags',   status: 'live' },
      { id: 'st3', name: 'Earnings Calendar',  description: 'Upcoming earnings for holdings',  status: 'beta' },
      { id: 'st4', name: 'Options Strategist', description: 'Trade-idea generator',            status: 'planned' },
    ],
    agents: [
      { name: 'price-watcher',        description: 'Polls quotes, fires alerts',           health: 'healthy', uptime: '99.95%', accuracy: 99, lastAction: 'NVDA crossed ₹X target',     lastRun: '1 min ago' },
      { name: 'earnings-summariser', description: 'Day-after earnings digest',              health: 'healthy', uptime: '98.8%', accuracy: 91, lastAction: 'Summarised TSLA earnings',     lastRun: '1 d ago' },
      { name: 'sentiment-tracker',   description: 'X / news sentiment per ticker',           health: 'degraded', uptime: '88.4%', accuracy: 78, lastAction: 'Twitter rate-limited',       lastRun: '2 hr ago' },
    ],
    feed: [
      { id: 'stf1', message: 'NVDA crossed ₹X (target hit)',                                time: '14:18' },
      { id: 'stf2', message: 'Watchlist: GOOGL down 1.8% on regulator news',                 time: '13:00' },
      { id: 'stf3', message: 'Earnings reminder: AAPL reports Wed after-market',             time: '09:30' },
    ],
  },

  health: {
    slug: 'health',
    title: 'Health & Fitness',
    emoji: '💪',
    tagline: 'Sleep · activity · vitals · habits',
    kpis: [
      { label: 'Sleep (last)',  value: '7 h 32 m', delta: '+18 m vs avg' },
      { label: 'Steps today',   value: '4,820',    delta: '60% of goal' },
      { label: 'Resting HR',    value: '62 bpm',   delta: 'within range' },
      { label: 'Workout streak', value: '11 days', delta: 'PB: 14 d' },
    ],
    applications: [
      { id: 'ha1', name: 'Sleep Log',          description: 'Last 30 d trends + score',         status: 'live' },
      { id: 'ha2', name: 'Workout Planner',    description: 'Auto-plans rest/intensity weeks',  status: 'beta' },
      { id: 'ha3', name: 'Nutrition Tracker',  description: 'Macros + meal logging',            status: 'beta' },
      { id: 'ha4', name: 'Body Composition',   description: 'Trends from smart scale',           status: 'planned' },
    ],
    agents: [
      { name: 'sleep-coach',     description: 'Personalised wind-down advice',                 health: 'healthy', uptime: '99.4%', accuracy: 86, lastAction: 'Suggested 22:30 lights-out', lastRun: '6 hr ago' },
      { name: 'workout-planner', description: 'Adjusts plan based on recovery',                health: 'healthy', uptime: '98.9%', accuracy: 84, lastAction: 'Swapped HIIT → mobility',       lastRun: '1 d ago' },
      { name: 'nutrition-tracker', description: 'Reads pantry, suggests meals',                 health: 'training', uptime: '92.1%', accuracy: 73, lastAction: 'Re-training on new logs',      lastRun: '2 d ago' },
    ],
    feed: [
      { id: 'hf1', message: 'Sleep score 84 (good). Deep sleep +12 min vs avg',                 time: '07:00' },
      { id: 'hf2', message: 'Tennis booked 5:30 pm — 1 hr cardio',                              time: '11:00' },
      { id: 'hf3', message: 'Water intake 0.6 L behind goal — drink 2 glasses by 3 pm',         time: '13:00' },
    ],
  },

  learning: {
    slug: 'learning',
    title: 'Learning · Second Brain',
    emoji: '📚',
    tagline: 'Notes · papers · highlights · knowledge graph',
    kpis: [
      { label: 'Notes total',     value: '4,218',    delta: '+12 this week' },
      { label: 'Reading queue',   value: '14 items', delta: '~18 hr to clear' },
      { label: 'Papers read MTD', value: '7',        delta: 'goal: 12' },
      { label: 'Streak',          value: '23 days',  delta: 'daily review' },
    ],
    applications: [
      { id: 'la1', name: 'Notion Vault',          description: 'Indexed search + RAG',           status: 'live' },
      { id: 'la2', name: 'Reading Queue',         description: 'Pocket / ArXiv / RSS unified',   status: 'live' },
      { id: 'la3', name: 'Flashcard Generator',   description: 'Anki-style cards from highlights', status: 'beta' },
      { id: 'la4', name: 'Knowledge Graph',       description: 'Concept-link explorer',           status: 'planned' },
    ],
    agents: [
      { name: 'note-indexer',   description: 'Embeds + semantically tags new notes',           health: 'healthy', uptime: '99.6%', accuracy: 95, lastAction: 'Indexed 12 new notes',        lastRun: '20 min ago' },
      { name: 'paper-summariser', description: 'TL;DR + claims for ArXiv papers',                health: 'healthy', uptime: '98.3%', accuracy: 89, lastAction: 'Summarised "RAG Survey 2026"', lastRun: '4 hr ago' },
      { name: 'recall-trainer', description: 'Spaced-repetition prompts at the right time',     health: 'healthy', uptime: '99.0%', accuracy: 91, lastAction: 'Sent 8 recall prompts',         lastRun: '6 hr ago' },
    ],
    feed: [
      { id: 'lf1', message: 'Indexed 12 new notes (Notion)',                                     time: '14:20' },
      { id: 'lf2', message: 'Paper summary ready: "Retrieval-Augmented Generation Survey 2026"', time: '10:00' },
      { id: 'lf3', message: 'Flashcards generated: 6 from highlights last night',                time: '07:30' },
    ],
  },

  home: {
    slug: 'home',
    title: 'Home & IoT',
    emoji: '🏠',
    tagline: 'Devices · automations · energy',
    kpis: [
      { label: 'Devices online', value: '14 / 16',  delta: '2 offline' },
      { label: 'Energy today',   value: '6.4 kWh',  delta: '−12% vs avg' },
      { label: 'Active scenes',  value: '3',        delta: 'Evening, Away, Sleep' },
      { label: 'Alerts open',    value: '1',        delta: 'fridge door left open' },
    ],
    applications: [
      { id: 'hoa1', name: 'Device Map',         description: 'All sensors + actuators by room', status: 'live' },
      { id: 'hoa2', name: 'Automation Rules',   description: 'If-this-then-that builder',        status: 'live' },
      { id: 'hoa3', name: 'Energy Monitor',     description: 'Per-circuit consumption + cost',   status: 'beta' },
      { id: 'hoa4', name: 'Security Dashboard', description: 'Cameras, locks, motion',           status: 'planned' },
    ],
    agents: [
      { name: 'scene-runner',    description: 'Triggers scenes by time/presence',                health: 'healthy', uptime: '99.95%', accuracy: 99, lastAction: 'Ran "Evening" scene',         lastRun: '2 hr ago' },
      { name: 'energy-coach',    description: 'Suggests load shifts to off-peak',                health: 'healthy', uptime: '98.2%', accuracy: 87, lastAction: 'Recommended shift to 22:00',   lastRun: '4 hr ago' },
      { name: 'anomaly-watcher', description: 'Detects unusual device behaviour',                 health: 'degraded', uptime: '95.0%', accuracy: 82, lastAction: 'Flagged fridge alert',        lastRun: '12 min ago' },
    ],
    feed: [
      { id: 'hof1', message: 'Fridge door left open > 5 min',                                    time: '14:30' },
      { id: 'hof2', message: 'Evening scene ran — lights 40%, AC 24°C',                          time: '12:00' },
      { id: 'hof3', message: 'AC unit (bedroom) drawing 18% more than baseline',                  time: '10:00' },
    ],
  },

  travel: {
    slug: 'travel',
    title: 'Travel',
    emoji: '✈️',
    tagline: 'Trips · bookings · expenses · packing',
    kpis: [
      { label: 'Upcoming trips', value: '2',         delta: 'next: 12 May' },
      { label: 'Miles balance',  value: '142,300',   delta: '+12k MTD' },
      { label: 'Open bookings',  value: '5',         delta: 'flights + hotels' },
      { label: 'Travel spend YTD', value: '₹4.8 L',   delta: 'budget 50%' },
    ],
    applications: [
      { id: 'ta1', name: 'Trip Planner',     description: 'Itinerary + reservations in one view', status: 'live' },
      { id: 'ta2', name: 'Booking Tracker',  description: 'PNRs, hotel bookings, refunds',         status: 'live' },
      { id: 'ta3', name: 'Packing Lists',    description: 'Auto-generated by trip type/weather',   status: 'beta' },
      { id: 'ta4', name: 'Expense Splitter', description: 'Family/friends trip cost split',         status: 'planned' },
    ],
    agents: [
      { name: 'fare-watcher',    description: 'Alerts on price drops for routes',                 health: 'healthy', uptime: '99.4%', accuracy: 93, lastAction: 'Found ₹2,400 cheaper BLR→GOA',  lastRun: '1 hr ago' },
      { name: 'itinerary-builder', description: 'Drafts full itineraries from prompts',            health: 'healthy', uptime: '98.7%', accuracy: 88, lastAction: 'Drafted 3-day Goa plan',         lastRun: '3 d ago' },
      { name: 'visa-tracker',    description: 'Watches visa requirements + expiry',                health: 'healthy', uptime: '99.0%', accuracy: 96, lastAction: 'Checked Schengen rules',         lastRun: '5 d ago' },
    ],
    feed: [
      { id: 'tf1', message: 'BLR → GOA fare dropped: ₹4,200 (was ₹6,600)',                        time: '13:00' },
      { id: 'tf2', message: 'Hotel booking confirmed: Park Hyatt Goa, 12–15 May',                  time: '10:00' },
      { id: 'tf3', message: 'Itinerary v2 ready for "Goa weekend"',                                 time: '09:00' },
    ],
  },
};

// ── Sidebar nav config ─────────────────────────────────────────────
export interface NavItem {
  to: string;
  label: string;
  icon: string;
  domain?: string;
}
export const navItems: NavItem[] = [
  { to: '/',          label: 'Dashboard',         icon: '▣' },
  { to: '/finance',   label: 'Personal Finance',  icon: '$', domain: 'finance' },
  { to: '/shopify',   label: 'Shopify Store',     icon: '🛒', domain: 'shopify' },
  { to: '/stocks',    label: 'Stock Market',      icon: '↗', domain: 'stocks' },
  { to: '/health',    label: 'Health & Fitness',  icon: '💪', domain: 'health' },
  { to: '/learning',  label: 'Learning',          icon: '📚', domain: 'learning' },
  { to: '/home-iot',  label: 'Home & IoT',        icon: '🏠', domain: 'home' },
  { to: '/travel',    label: 'Travel',            icon: '✈️', domain: 'travel' },
];
