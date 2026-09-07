export const meta = {
  name: 'dev-team-pipeline',
  description: '28-30 stage dev-team pipeline per feature; same specialist role never runs concurrently across features',
  phases: [
    { title: 'Design' },
    { title: 'Build' },
    { title: 'Audit' },
    { title: 'Test' },
    { title: 'Harden' },
    { title: 'Ship' },
  ],
}

const OPUS = 'claude-opus-5'
const HAIKU = 'claude-haiku-4-5-20251001'

const DENY_PREFIXES = [
  'backend/src/auth/', 'backend/src/middleware/', 'backend/src/services/ai.py',
  'backend/src/services/gateway.py', 'backend/alembic/env.py',
  '.github/workflows/', '.claude/hooks/', '.claude/agents/', '.claude/commands/',
  '.claude/settings.json', 'render.yaml', 'vercel.json',
  'CLAUDE.md', 'tasks/process-hierarchy.md', 'tasks/last-gate-report.md',
  'tasks/lessons.md', 'tasks/.feature-counter',
]

// Agents sometimes return absolute paths (e.g. "/home/user/Arshad.AI/frontend/...")
// even when asked for repo-relative ones. Strip the project root before any
// denylist/traversal check so a legitimate absolute path isn't mistaken for a
// path-escape attempt — a real ".." or a genuine leading "/" outside the
// project root still gets caught after normalization.
const PROJECT_ROOT_PREFIX = '/home/user/Arshad.AI/'
function normalizePath(p) {
  if (typeof p !== 'string') return p
  return p.startsWith(PROJECT_ROOT_PREFIX) ? p.slice(PROJECT_ROOT_PREFIX.length) : p
}

function denylistHits(files) {
  return (files || []).filter(f => {
    const p = normalizePath(f.path || '')
    if (p.includes('..') || p.startsWith('/') || p.startsWith('~') || p.includes('$')) return true
    if (p === 'backend/src/main.py') return false
    return DENY_PREFIXES.some(pre => p === pre || p.startsWith(pre))
  })
}

function mergeFiles(base, updates) {
  const map = new Map(base.map(f => [f.path, f]))
  for (const f of (updates || [])) {
    const path = normalizePath(f.path)
    map.set(path, { ...f, path })
  }
  return Array.from(map.values())
}

// Per-role mutex shared across every feature running in this workflow —
// guarantees the same specialist agent role never executes concurrently
// for two different features.
const locks = {}
function withRole(role, fn) {
  const prior = locks[role] || Promise.resolve()
  const p = prior.then(fn, fn)
  locks[role] = p.catch(() => {})
  return p
}

const FILES_SCHEMA = {
  type: 'object',
  properties: {
    files: { type: 'array', items: { type: 'object', properties: { path: { type: 'string' }, content: { type: 'string' } }, required: ['path', 'content'] } },
    summary: { type: 'string' },
  },
  required: ['summary'],
}

const DECISION_SCHEMA = {
  type: 'object',
  properties: {
    decision: { type: 'string', enum: ['approved', 'approved_with_caveats', 'rejected'] },
    blocking: { type: 'boolean' },
    concerns: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['decision'],
}

const DEFECTS_SCHEMA = {
  type: 'object',
  properties: {
    defects: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, description: { type: 'string' }, severity: { type: 'string' } }, required: ['file', 'description'] } },
    all_clear: { type: 'boolean' },
  },
  required: ['defects', 'all_clear'],
}

const SECURITY_SCHEMA = {
  type: 'object',
  properties: {
    files: { type: 'array', items: { type: 'object', properties: { path: { type: 'string' }, content: { type: 'string' } }, required: ['path', 'content'] } },
    findings: { type: 'array', items: { type: 'object', properties: { description: { type: 'string' }, escalate: { type: 'boolean' } }, required: ['description', 'escalate'] } },
    summary: { type: 'string' },
  },
  required: ['summary', 'findings'],
}

function ctxHeader(f, stageName) {
  return `Feature ${f.featId} — ${stageName}\n\nRequirement: ${f.requirement}\n`
}

function dump(files) {
  return (files || []).map(x => `--- ${x.path} ---\n${x.content}`).join('\n\n')
}

async function runFeaturePipeline(f) {
  const log_ = (m) => log(`[${f.featId}] ${m}`)
  let codebase_context = f.seed && f.seed.codebase_context
  let bpdd = f.seed && f.seed.bpdd
  let code = []
  let halt = null

  phase('Design')

  if (!codebase_context) {
    log_('Code Explorer')
    const r = await withRole('code-explorer', () => agent(
      `${ctxHeader(f, 'Code Explorer')}\nScan the codebase for existing patterns, module boundaries, naming idioms, and analogous features relevant to this requirement. Return JSON: {codebase_context: {...findings}}.`,
      { agentType: 'code-explorer', phase: 'Design', schema: { type: 'object', properties: { codebase_context: { type: 'object' } }, required: ['codebase_context'] } }
    ))
    codebase_context = r && r.codebase_context
  } else {
    log_('Code Explorer — skipped (seeded)')
  }

  if (!bpdd) {
    log_('Business Analyst')
    const r = await withRole('business-analyst', () => agent(
      `${ctxHeader(f, 'Business Analyst')}\nCodebase context: ${JSON.stringify(codebase_context)}\nProduce an RTM + BPDD. Return JSON: {bpdd:{...}, feature_name, domain, sub_section}.`,
      { agentType: 'business-analyst', model: HAIKU, phase: 'Design', schema: { type: 'object', properties: { bpdd: { type: 'object' }, feature_name: { type: 'string' }, domain: { type: 'string' }, sub_section: { type: 'string' } }, required: ['bpdd', 'feature_name', 'domain', 'sub_section'] } }
    ))
    bpdd = r
  } else {
    log_('Business Analyst — skipped (seeded)')
  }

  log_('EA pre-build')
  const eaPre = await withRole('enterprise-architect', () => agent(
    `${ctxHeader(f, 'Enterprise Architect pre-build')}\nBPDD: ${JSON.stringify(bpdd)}\nReview architectural alignment BEFORE any code is written. Return decision.`,
    { agentType: 'enterprise-architect', phase: 'Design', schema: DECISION_SCHEMA }
  ))
  if (eaPre && eaPre.decision === 'rejected') {
    return { featId: f.featId, status: 'halted', reason: `EA pre-build rejected: ${eaPre.notes || ''}` }
  }

  log_('AI Engineer / Tech Lead')
  const aiEng = await withRole('ai-engineer', () => agent(
    `${ctxHeader(f, 'AI Engineer / Tech Lead')}\nBPDD: ${JSON.stringify(bpdd)}\nEA pre-build: ${JSON.stringify(eaPre)}\nChallenge decisions, flag scaling risks, set architecture direction the Solution Architect must follow. Return JSON: {implementation_plan: string, tech_lead_review: string}.`,
    { agentType: 'ai-engineer', model: OPUS, phase: 'Design', schema: { type: 'object', properties: { implementation_plan: { type: 'string' }, tech_lead_review: { type: 'string' } }, required: ['implementation_plan'] } }
  ))

  log_('Solution Architect')
  let sa = await withRole('solution-architect', () => agent(
    `${ctxHeader(f, 'Solution Architect')}\nBPDD: ${JSON.stringify(bpdd)}\nTech Lead plan: ${JSON.stringify(aiEng)}\nCodebase context: ${JSON.stringify(codebase_context)}\nProduce an SDD (components, data models, endpoints, technical approach) the Developer will follow strictly. Return JSON: {sdd: {...}}.`,
    { agentType: 'solution-architect', phase: 'Design', schema: { type: 'object', properties: { sdd: { type: 'object' } }, required: ['sdd'] } }
  ))
  let sdd = sa && sa.sdd

  log_('Architecture Critic')
  let archCritic = await withRole('architecture-critic', () => agent(
    `${ctxHeader(f, 'Architecture Critic')}\nSDD: ${JSON.stringify(sdd)}\nCodebase context: ${JSON.stringify(codebase_context)}\nAdversarially review the SDD. Flag over-engineering, coupling risk, convention deviations. Return decision; set blocking:true only for genuinely blocking issues.`,
    { agentType: 'architecture-critic', model: OPUS, phase: 'Design', schema: DECISION_SCHEMA }
  ))

  // Redesign loop: a blocking verdict here means real bugs the SDD would have
  // shipped, not a reason to force through. Feed the findings back to Solution
  // Architect for a corrected SDD and re-review, capped at 2 extra rounds — if
  // it's still blocking after that, it needs human review, not more retries.
  let archIter = 0
  while (archCritic && archCritic.blocking && archIter < 2) {
    archIter++
    log_(`Architecture Critic blocked (redesign iteration ${archIter})`)
    sa = await withRole('solution-architect', () => agent(
      `${ctxHeader(f, `Solution Architect — redesign iteration ${archIter}`)}\nBPDD: ${JSON.stringify(bpdd)}\nTech Lead plan: ${JSON.stringify(aiEng)}\nCodebase context (a SUMMARY gathered before this feature's code existed — it may now be stale; you have Read and Grep tools, use them): ${JSON.stringify(codebase_context)}\n\nYour PREVIOUS SDD — PATCH this, do not regenerate from scratch. Keep every part that wasn't flagged:\n${JSON.stringify(sdd)}\n\nThe Architecture Critic rejected it with these BLOCKING findings. Each one cites specific files and often specific line numbers — READ THE ACTUAL FILE AT EACH CITED PATH RIGHT NOW before writing your revision. Do not trust the summary text alone; line numbers may have shifted and other agents may have changed these files since your last pass. Verify the current real content, then fix it for real:\n${JSON.stringify(archCritic.concerns)}\n${archCritic.notes || ''}\n\nProduce a corrected SDD that resolves every finding above while preserving everything from the previous SDD that wasn't flagged. Return JSON: {sdd: {...}}.`,
      { agentType: 'solution-architect', phase: 'Design', schema: { type: 'object', properties: { sdd: { type: 'object' } }, required: ['sdd'] } }
    ))
    sdd = sa && sa.sdd
    archCritic = await withRole('architecture-critic', () => agent(
      `${ctxHeader(f, `Architecture Critic — re-review iteration ${archIter}`)}\nSDD: ${JSON.stringify(sdd)}\nCodebase context: ${JSON.stringify(codebase_context)}\nThis SDD was revised specifically to address your prior blocking findings. Re-review adversarially — do not rubber-stamp; set blocking:true again if the revision doesn't genuinely fix the issues or introduces new ones.`,
      { agentType: 'architecture-critic', model: OPUS, phase: 'Design', schema: DECISION_SCHEMA }
    ))
  }
  if (archCritic && archCritic.blocking) {
    return { featId: f.featId, status: 'halted', reason: `Architecture Critic still blocking after ${archIter} redesign iteration(s): ${(archCritic.concerns || []).join('; ')}` }
  }

  log_('System Engineer')
  const sysEng = await withRole('system-architect', () => agent(
    `${ctxHeader(f, 'System Engineer')}\nSDD: ${JSON.stringify(sdd)}\nArchitecture Critic concerns: ${JSON.stringify(archCritic)}\nDesign system architecture, component structure, data flow, schema, caching strategy. Return JSON: {system_design:{...}}.`,
    { agentType: 'system-architect', model: OPUS, phase: 'Design', schema: { type: 'object', properties: { system_design: { type: 'object' } }, required: ['system_design'] } }
  ))

  phase('Build')

  log_('Engineer (MVP)')
  const eng = await withRole('fullstack-developer', () => agent(
    `${ctxHeader(f, 'Engineer')}\nSDD: ${JSON.stringify(sdd)}\nSystem design: ${JSON.stringify(sysEng)}\nCodebase context: ${JSON.stringify(codebase_context)}\nBuild a production-ready MVP. Return files (path+content) and a summary.`,
    { agentType: 'fullstack-developer', phase: 'Build', schema: FILES_SCHEMA }
  ))
  code = mergeFiles(code, eng && eng.files)
  { const hits = denylistHits(eng && eng.files); if (hits.length) return { featId: f.featId, status: 'halted', reason: `Denylist violation at Engineer: ${hits.map(h => h.path).join(', ')}` } }

  log_('Developer')
  const dev = await withRole('developer', () => agent(
    `${ctxHeader(f, 'Developer')}\nSDD: ${JSON.stringify(sdd)}\nEngineer output summary: ${eng && eng.summary}\nCurrent files: ${JSON.stringify(code.map(x => x.path))}\nGenerate/complete the feature code. Return files (path+content) and a summary.`,
    { agentType: 'developer', phase: 'Build', schema: FILES_SCHEMA }
  ))
  code = mergeFiles(code, dev && dev.files)
  { const hits = denylistHits(dev && dev.files); if (hits.length) return { featId: f.featId, status: 'halted', reason: `Denylist violation at Developer: ${hits.map(h => h.path).join(', ')}` } }

  phase('Audit')

  const auditStages = [
    { role: 'database-specialist', label: 'Database Specialist', ask: 'Audit every DB interaction — queries, indexes, ORM, migrations, N+1, unsafe SQL. Fix issues found (empty files array if none apply).' },
    { role: 'python-specialist', label: 'Python Specialist', ask: 'Audit async correctness, FastAPI DI, Pydantic v2, exceptions, type annotations. Fix issues found (empty files array if none apply).' },
    { role: 'code-reviewer', label: 'Code Reviewer', ask: 'Review against CLAUDE.md rules (api.md, database.md, frontend.md) — naming, error shapes, async patterns, UUIDs. Fix departures.', model: OPUS },
    { role: 'frontend-developer', label: 'Frontend Engineer', ask: 'Apply the frontend-design skill: bold aesthetic direction, distinctive typography/colour/motion, all 4 states (loading/empty/error/content), accessible, reusable.' },
    { role: 'type-design-analyzer', label: 'Type Design Analyzer', ask: 'Audit the type system for weak types, missing invariant encoding, illegal-state prevention. Improve types.' },
    { role: 'code-analyzer', label: 'Senior Engineer', ask: 'Code quality audit — N+1, bad patterns, scalability risks. NO functionality changes.', model: OPUS },
    { role: 'refactoring-specialist', label: 'Software Architect', ask: 'Restructure to separate concerns, reduce coupling, increase modularity. NO functionality changes.', model: OPUS },
    { role: 'silent-failure-hunter', label: 'Silent Failure Hunter', ask: 'Find swallowed exceptions, HTTP 200 masking errors, missing propagation. Fix them.' },
    { role: 'code-simplifier', label: 'Code Simplifier', ask: 'Eliminate unnecessary abstraction, over-engineering, verbose constructs. Preserve all functionality.', model: OPUS },
  ]

  for (const st of auditStages) {
    log_(st.label)
    const r = await withRole(st.role, () => agent(
      `${ctxHeader(f, st.label)}\n${st.ask}\nCurrent files:\n${dump(code)}`,
      { agentType: st.role, model: st.model, phase: 'Audit', schema: FILES_SCHEMA }
    ))
    code = mergeFiles(code, r && r.files)
    const hits = denylistHits(r && r.files)
    if (hits.length) return { featId: f.featId, status: 'halted', reason: `Denylist violation at ${st.label}: ${hits.map(h => h.path).join(', ')}` }
  }

  log_('Process Organiser')
  const po = await withRole('process-organiser', () => agent(
    `${ctxHeader(f, 'Process Organiser')}\nFeature: ${bpdd && bpdd.feature_name}, domain=${bpdd && bpdd.domain}, sub_section=${bpdd && bpdd.sub_section}.\nEcho back a structured PHEntry confirming metadata, or WARNING:<reason> in feature_name if something is inconsistent.`,
    { agentType: 'process-organiser', model: HAIKU, phase: 'Audit', schema: { type: 'object', properties: { feature_name: { type: 'string' }, domain: { type: 'string' }, sub_section: { type: 'string' } }, required: ['feature_name'] } }
  ))
  if (po && typeof po.feature_name === 'string' && po.feature_name.startsWith('WARNING:')) {
    return { featId: f.featId, status: 'halted', reason: po.feature_name }
  }

  phase('Test')

  log_('Test Architect')
  const testArch = await withRole('test-architect', () => agent(
    `${ctxHeader(f, 'Test Architect')}\nBPDD: ${JSON.stringify(bpdd)}\nSDD: ${JSON.stringify(sdd)}\nDesign test architecture: unit vs integration boundaries, mock strategy, coverage plan. Return JSON: {test_plan:{...}}.`,
    { agentType: 'test-architect', phase: 'Test', schema: { type: 'object', properties: { test_plan: { type: 'object' } }, required: ['test_plan'] } }
  ))

  log_('Test Script Writer')
  const tsw = await withRole('test-script-writer', () => agent(
    `${ctxHeader(f, 'Test Script Writer')}\nBPDD: ${JSON.stringify(bpdd)}\nTest plan: ${JSON.stringify(testArch)}\nWrite test scripts covering every RTM acceptance criterion plus edge cases. Return files (test file path+content) and summary.`,
    { agentType: 'test-script-writer', phase: 'Test', schema: FILES_SCHEMA }
  ))
  code = mergeFiles(code, tsw && tsw.files)

  log_('PR Test Analyzer')
  const prTest = await withRole('pr-test-analyzer', () => agent(
    `${ctxHeader(f, 'PR Test Analyzer')}\nAssess whether tests cover happy/error/edge paths from the BPDD. Fix/add missing tests.\nCurrent test files:\n${dump(code.filter(x => x.path.includes('test')))}`,
    { agentType: 'pr-test-analyzer', phase: 'Test', schema: FILES_SCHEMA }
  ))
  code = mergeFiles(code, prTest && prTest.files)

  log_('Tester (iteration 0)')
  let tester = await withRole('tester', () => agent(
    `${ctxHeader(f, 'Tester iteration 0')}\nStatically execute the test scripts against this code by reading it and reasoning about behaviour. Report defects.\nCode:\n${dump(code)}`,
    { agentType: 'tester', phase: 'Test', schema: DEFECTS_SCHEMA }
  ))

  phase('Harden')

  let iter = 0
  while (tester && !tester.all_clear && (tester.defects || []).length && iter < 5) {
    iter++
    log_(`Bug-fix loop iteration ${iter}`)
    const fix = await withRole('bug-fixer', () => agent(
      `${ctxHeader(f, `Bug Fixer iteration ${iter}`)}\nDefects: ${JSON.stringify(tester.defects)}\nCode:\n${dump(code)}\nProduce a revision that closes every defect.`,
      { agentType: 'bug-fixer', phase: 'Harden', schema: FILES_SCHEMA }
    ))
    code = mergeFiles(code, fix && fix.files)
    const hits = denylistHits(fix && fix.files)
    if (hits.length) return { featId: f.featId, status: 'halted', reason: `Denylist violation at BugFixer iter ${iter}: ${hits.map(h => h.path).join(', ')}` }

    tester = await withRole('tester', () => agent(
      `${ctxHeader(f, `Tester verify iteration ${iter}`)}\nRe-run the test scripts against the updated code. Report remaining defects.\nCode:\n${dump(code)}`,
      { agentType: 'tester', phase: 'Harden', schema: DEFECTS_SCHEMA }
    ))
  }
  if (tester && !tester.all_clear && (tester.defects || []).length) {
    halt = `Bug-fix loop exhausted 5 iterations with defects remaining: ${(tester.defects || []).map(d => d.description).join('; ')}`
  }

  log_('Debugger (always runs)')
  const dbg = await withRole('debugger', () => agent(
    `${ctxHeader(f, 'Debugger')}\nRemaining defects (if any): ${JSON.stringify(tester && tester.defects)}\nRoot-cause and robustly fix anything remaining.\nCode:\n${dump(code)}`,
    { agentType: 'debugger', model: OPUS, phase: 'Harden', schema: FILES_SCHEMA }
  ))
  code = mergeFiles(code, dbg && dbg.files)
  if (dbg && dbg.summary && /resolved|fixed|clear/i.test(dbg.summary)) halt = null

  log_('Performance Optimisation Engineer')
  const perf = await withRole('performance-engineer', () => agent(
    `${ctxHeader(f, 'Performance Optimisation Engineer')}\nEliminate bottlenecks — N+1, missing indexes, async gaps, memory leaks.\nCode:\n${dump(code)}`,
    { agentType: 'performance-engineer', phase: 'Harden', schema: FILES_SCHEMA }
  ))
  code = mergeFiles(code, perf && perf.files)

  log_('Security Auditor')
  const sec = await withRole('security-auditor', () => agent(
    `${ctxHeader(f, 'Security Auditor')}\nOWASP Top 10 audit. Fix insecure implementations. Set escalate:true on any finding that must block ship.\nCode:\n${dump(code)}`,
    { agentType: 'security-auditor', model: OPUS, phase: 'Harden', schema: SECURITY_SCHEMA }
  ))
  code = mergeFiles(code, sec && sec.files)
  const securityHalt = !!(sec && (sec.findings || []).some(x => x.escalate))

  log_('DevOps Engineer')
  const devops = await withRole('devops-engineer', () => agent(
    `${ctxHeader(f, 'DevOps Engineer')}\nPrepare for production deployment — monitoring, scaling, deployment checklist.\nSecurity report: ${JSON.stringify(sec && sec.summary)}\nCode:\n${dump(code)}`,
    { agentType: 'devops-engineer', phase: 'Harden', schema: FILES_SCHEMA }
  ))
  code = mergeFiles(code, devops && devops.files)

  log_('Production Validator')
  const prodVal = await withRole('production-validator', () => agent(
    `${ctxHeader(f, 'Production Validator')}\nVerify full production-readiness — no stubs, no TODOs, all endpoints functional, no debug code.\nDevOps report: ${JSON.stringify(devops && devops.summary)}\nSecurity report: ${JSON.stringify(sec && sec.summary)}\nCode:\n${dump(code)}`,
    { agentType: 'production-validator', phase: 'Harden', schema: { type: 'object', properties: { blocking: { type: 'boolean' }, notes: { type: 'string' }, files: FILES_SCHEMA.properties.files }, required: ['blocking'] } }
  ))
  code = mergeFiles(code, prodVal && prodVal.files)
  if (prodVal && prodVal.blocking) halt = (halt ? halt + '; ' : '') + `Production Validator blocking: ${prodVal.notes || ''}`

  phase('Ship')

  log_('Enterprise Architect post-build')
  const eaPost = await withRole('enterprise-architect', () => agent(
    `${ctxHeader(f, 'Enterprise Architect post-build')}\nBPDD: ${JSON.stringify(bpdd)}\nSDD: ${JSON.stringify(sdd)}\nFiles built: ${code.map(x => x.path).join(', ')}\nHalt reason so far: ${halt || 'none'}\nSecurity halt: ${securityHalt}\nGive final SHIP/FIX/BLOCK-style sign-off.`,
    { agentType: 'enterprise-architect', phase: 'Ship', schema: DECISION_SCHEMA }
  ))

  if (securityHalt) {
    return { featId: f.featId, status: 'halted', reason: 'Unresolved security escalations from Security Auditor.', code, bpdd, sdd }
  }
  if (eaPost && eaPost.decision === 'rejected') {
    return { featId: f.featId, status: 'halted', reason: `EA post-build rejected: ${eaPost.notes || halt || ''}`, code, bpdd, sdd }
  }

  return {
    featId: f.featId,
    status: 'completed',
    haltNote: halt,
    eaDecision: eaPost && eaPost.decision,
    bugFixIterations: iter,
    code,
    bpdd,
    sdd,
    branch: f.branch || `dev-team/${f.featId.toLowerCase()}-${((bpdd && bpdd.feature_name) || f.requirement).toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 50)}`,
  }
}

const outcomes = []
for (const f of (args && args.features) || []) {
  outcomes.push(runFeaturePipeline(f).catch(e => ({ featId: f.featId, status: 'error', error: String((e && e.message) || e) })))
}
const results = await Promise.all(outcomes)

for (const r of results) {
  if (r.status !== 'completed') { log(`${r.featId}: ${r.status} — ${r.reason || r.error || ''}`); continue }
  log(`${r.featId}: writing files and committing to ${r.branch}`)
  await withRole('general-purpose-commit', () => agent(
    `Write these files to disk under /home/user/Arshad.AI/, then commit and push.\n\nFiles:\n${dump(r.code)}\n\nSteps:\n1. Use the Write tool to write each file at its exact path (relative to /home/user/Arshad.AI/).\n2. Run: git checkout -b ${r.branch} 2>/dev/null || git checkout ${r.branch}\n3. git add each written file by path.\n4. git commit -m "feat(${r.featId}): ${((r.bpdd && r.bpdd.feature_name) || r.featId)}\\n\\nGenerated by dev-team pipeline (workflow).\\n\\nCo-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"\n5. git push -u origin ${r.branch}\n6. Append one row to tasks/pipeline-runs.md (create with a header row if absent): feature id, short requirement, status=completed, EA decision=${r.eaDecision}, bug-fix iterations=${r.bugFixIterations}.\nReport the result of each step.`,
    { agentType: 'general-purpose', phase: 'Ship' }
  ))
}

return results.map(r => ({ featId: r.featId, status: r.status, reason: r.reason || r.error, eaDecision: r.eaDecision, branch: r.branch }))
