### ⚠️ GATE PASSED WITH WARNINGS — Ready for merge

**FEAT-147 (dead dashboard controls) and FEAT-140 (verified already done)**

Eight agents ran: code-reviewer, security-auditor, debugger, test-writer, refactorer, doc-writer, silent-failure-hunter, pr-test-analyzer. No Critical findings. Every security finding was fixed.

**Verdict: WARN.**

Changes:
- Quick actions and Knowledge search open a new chat with the text prefilled. Nothing sends until the user presses Send.
- The Agent activity card says "recent runs" and no longer shows a pulsing live dot.
- FEAT-140 needed no code: Home and IoT, Learning and Travel already use the Coming soon page on main. Tracker rows for FEAT-140 and FEAT-147 are updated.

Fixed after the gate:
- SEC-001: after a failed chat start the typed text leaves browser history and is kept in page state.
- SEC-002: the Knowledge search input is capped at 500 characters.
- A non-string `draft` in router state is ignored (it could crash the composer).
- A blank Knowledge search now shows a hint and keeps the user on the page.
- Loading (`null`) states render a skeleton in both cards instead of a blank card.
- The hand-off to chat is one shared hook, `useHandOffToChat`, used by both cards and the top bar.
- The Quick actions label rule is documented in a comment.
- Tests: 12 new, covering null states, the Open chat label rule, blank and trimmed submit, the length cap, and the Chat page retry and non-string draft. Frontend 531 pass, `tsc` clean.

Checked and not a bug: the suspected stuck "Creating chat…" page when capturing from `/chat/<id>`. A test shows React Router remounts the page, so it works. The test stays as a guard.

Deferred warnings:
- [ ] "Open chatbot" is still recognised by its label text. A stable action type needs a backend field and a seed change.
- [ ] Quick actions only paste their label. They do not run the action, for example "Add task" does not create a task.
- [ ] Stale text in `CLAUDE.md` (file map, route count, mockData and services notes), `README.md` and the `mockData.ts` header. Not part of this change.
- [ ] The top bar quick capture has no blank-input hint. Not changed here.
- [ ] Session start failure message gives no cause or sign-in link.
