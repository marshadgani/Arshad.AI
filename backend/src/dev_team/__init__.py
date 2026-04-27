"""AI Dev Team Orchestration System.

A 9-agent pipeline that turns a feature requirement into:
  - structured requirements (RTM + BPDD)
  - architecture review (pre + post)
  - solution design (SDD)
  - generated feature code (sandbox)
  - process hierarchy update
  - test scripts
  - tested code with defects fixed

Trigger: `python -m src.dev_team.cli "<requirement>"`. Auto-invoked by
Claude Code per CLAUDE.md §21 whenever the user gives a feature requirement.

Generated code lives in tasks/agent-outputs/dev/<FEAT-NNN>/ and never
touches the real source tree until the user manually merges.
"""
