"""Process-wide configuration seams.

Modules here own the reading of environment variables that more than one
layer needs. Nothing in this package imports from `auth`, `integrations`,
`models`, or `services` — it is the bottom of the dependency graph, so any
layer may depend on it without creating a cycle.
"""
