// Pure-logic coverage for the Audit-phase domain-detection/skip/scope
// mechanism added 2026-10-05. The functions under test are duplicated here
// rather than imported, because dev-team-pipeline.js has a top-level
// `return` statement (it's executed by the Workflow tool's own runtime,
// not loaded as a standard ES module) — a normal `import` of it fails
// with "Illegal return statement" before any test can run. The rest of
// the file depends on host-injected Workflow globals (agent(), withRole(),
// phase(), log()) that have no mock/test harness in this repo at all,
// which is a separate, pre-existing, accepted gap for Workflow scripts in
// general — this file covers only the decomposable, pure part.
//
// This file exists because the gate review on 2026-10-05 found that gap
// unacceptable specifically for *this* change: it introduces real
// conditional branching (which agent runs, and what it sees), not just a
// data-value substitution, and a prior version of this logic shipped a
// real Critical bug (stale domain-detection snapshot) that a test like
// this would have caught immediately.
//
// The drift-guard test below keeps the duplication honest: if the real
// file's logic changes and this copy isn't updated to match, that test
// fails loudly instead of this file silently testing stale logic forever.
//
// Run with: node --test .claude/workflows/dev-team-pipeline.test.js

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const PIPELINE_PATH = fileURLToPath(new URL('./dev-team-pipeline.js', import.meta.url))

// --- Verbatim copy of the logic under test (see file header) --------------

const isFrontendFile = p => p.startsWith('frontend/') || /\.(tsx?|jsx?|css|scss)$/.test(p)
const computeSignals = c => ({
  touchesPython: c.some(x => x.path.endsWith('.py')),
  touchesFrontend: c.some(x => isFrontendFile(x.path)),
})

test('drift guard: the real file still contains this exact logic', () => {
  const src = readFileSync(PIPELINE_PATH, 'utf8')
  assert.ok(
    src.includes("const isFrontendFile = p => p.startsWith('frontend/') || /\\.(tsx?|jsx?|css|scss)$/.test(p)"),
    'isFrontendFile logic in dev-team-pipeline.js no longer matches this test file\'s copy — update both together'
  )
  assert.ok(
    src.includes('touchesPython: c.some(x => x.path.endsWith(\'.py\'))') &&
    src.includes('touchesFrontend: c.some(x => isFrontendFile(x.path))'),
    'computeSignals logic in dev-team-pipeline.js no longer matches this test file\'s copy — update both together'
  )
  assert.ok(
    src.includes("when: s => s.touchesPython") && src.includes("role: 'database-specialist'"),
    'database-specialist must stay gated on touchesPython, not a narrower DB-path heuristic (2026-10-05 security-gap fix) — update this test if that\'s intentionally changed'
  )
})

// --- isFrontendFile ---------------------------------------------------------

test('isFrontendFile classifies by frontend/ prefix', () => {
  assert.equal(isFrontendFile('frontend/src/App.tsx'), true)
  assert.equal(isFrontendFile('frontend/styles/main.css'), true)
  assert.equal(isFrontendFile('backend/src/main.py'), false)
})

test('isFrontendFile classifies by extension regardless of directory', () => {
  for (const ext of ['tsx', 'ts', 'jsx', 'js', 'css', 'scss']) {
    assert.equal(isFrontendFile(`some/path/file.${ext}`), true, `.${ext} should match`)
  }
  for (const ext of ['py', 'sql', 'md', 'json']) {
    assert.equal(isFrontendFile(`some/path/file.${ext}`), false, `.${ext} should not match`)
  }
})

// --- computeSignals ---------------------------------------------------------

test('computeSignals: all-backend file list', () => {
  const signals = computeSignals([{ path: 'backend/src/api/v1/foo.py', content: '' }])
  assert.equal(signals.touchesPython, true)
  assert.equal(signals.touchesFrontend, false)
})

test('computeSignals: all-frontend file list', () => {
  const signals = computeSignals([{ path: 'frontend/src/Foo.tsx', content: '' }])
  assert.equal(signals.touchesPython, false)
  assert.equal(signals.touchesFrontend, true)
})

test('computeSignals: mixed file list touches both domains', () => {
  const signals = computeSignals([
    { path: 'backend/src/api/v1/foo.py', content: '' },
    { path: 'frontend/src/Foo.tsx', content: '' },
  ])
  assert.equal(signals.touchesPython, true)
  assert.equal(signals.touchesFrontend, true)
})

test('computeSignals: empty file list touches neither domain', () => {
  const signals = computeSignals([])
  assert.equal(signals.touchesPython, false)
  assert.equal(signals.touchesFrontend, false)
})

test('computeSignals: touchesPython fires regardless of which backend path the .py file lives under', () => {
  // Regression for the security-gap finding (2026-10-05): database-specialist
  // must not be gated on a narrow backend/src/models/|alembic/|.sql path
  // heuristic, since real query code commonly lives in route/service files.
  // The fix gates it on touchesPython instead — this test locks that in.
  const code = [{ path: 'backend/src/api/v1/dashboard.py', content: 'await session.execute(...)' }]
  assert.equal(computeSignals(code).touchesPython, true)
})

// --- Skip/catch-up decision logic -----------------------------------------
// Mirrors the exact two-pass structure in runFeaturePipeline's Audit phase
// (initial pass with when()/computeSignals(code), then a catch-up pass with
// finalSignals) without needing agent()/withRole() — this is the decision
// logic itself, not the agent-calling side effect.

function simulateAuditDecisions(initialCode, stageOutputs) {
  const auditStages = [
    { role: 'database-specialist', when: s => s.touchesPython },
    { role: 'python-specialist', when: s => s.touchesPython },
    { role: 'code-reviewer' },
    { role: 'frontend-developer', when: s => s.touchesFrontend },
    { role: 'type-design-analyzer', when: s => s.touchesFrontend },
  ]
  let code = initialCode
  const ran = []
  const caughtUp = []
  for (const st of auditStages) {
    if (st.when && !st.when(computeSignals(code))) continue
    ran.push(st.role)
    code = code.concat(stageOutputs[st.role] || [])
  }
  const finalSignals = computeSignals(code)
  for (const st of auditStages) {
    if (!st.when || ran.includes(st.role) || !st.when(finalSignals)) continue
    caughtUp.push(st.role)
  }
  return { ran, caughtUp }
}

test('skip logic: backend-only feature skips both frontend stages, runs both backend stages', () => {
  const { ran, caughtUp } = simulateAuditDecisions(
    [{ path: 'backend/src/api/v1/foo.py', content: '' }], {}
  )
  assert.deepEqual(ran, ['database-specialist', 'python-specialist', 'code-reviewer'])
  assert.deepEqual(caughtUp, [])
})

test('skip logic: frontend-only feature skips both backend stages, runs both frontend stages', () => {
  const { ran, caughtUp } = simulateAuditDecisions(
    [{ path: 'frontend/src/Foo.tsx', content: '' }], {}
  )
  assert.deepEqual(ran, ['code-reviewer', 'frontend-developer', 'type-design-analyzer'])
  assert.deepEqual(caughtUp, [])
})

test('catch-up: a domain introduced mid-loop by an unconditional stage gets audited on the catch-up pass', () => {
  // Regression for the Critical finding (2026-10-05): code-reviewer (no
  // `when`, runs unconditionally) can introduce the feature's first backend
  // file. database-specialist/python-specialist (earlier in the array) must
  // have already made their skip decision by then — this test locks in that
  // the catch-up pass still audits that file instead of it shipping unaudited.
  const { ran, caughtUp } = simulateAuditDecisions(
    [{ path: 'frontend/src/Foo.tsx', content: '' }],
    { 'code-reviewer': [{ path: 'backend/src/api/v1/new_helper.py', content: '' }] }
  )
  assert.deepEqual(ran, ['code-reviewer', 'frontend-developer', 'type-design-analyzer'])
  assert.deepEqual(caughtUp, ['database-specialist', 'python-specialist'])
})

test('catch-up: does nothing when no new domain appears after the initial pass', () => {
  const { caughtUp } = simulateAuditDecisions(
    [{ path: 'backend/src/api/v1/foo.py', content: '' }],
    { 'code-reviewer': [{ path: 'backend/src/api/v1/bar.py', content: '' }] }
  )
  assert.deepEqual(caughtUp, [])
})
