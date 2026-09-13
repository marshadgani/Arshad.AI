"""Dashboard service package — the read-side of the dashboard widgets.

Four layers, each depending only on the ones above it. The dependency
direction is one-way and enforced by convention; a cycle here would mean a
layer has been given a responsibility that belongs elsewhere.

===========================  ==================================================
Module                       Responsibility
===========================  ==================================================
``formatting``               Display formatting only: timezone resolution,
                             human-readable dates/durations, title cleaning,
                             repo-name extraction. Knows nothing about rows,
                             widgets, or the database.
``widget_types``             The typed contract between derivation and
                             ``schemas/dashboard.py`` — TypedDicts and the
                             narrowed Literal aliases. No behaviour.
``rows``                     Defensive accessors over untrusted ingested rows
                             (verbatim third-party JSONB), plus the
                             ``project_all`` fault-isolation loop. Knows about
                             row shape, not about widgets.
``heuristics``               Business policy: which Gmail labels mean "urgent",
                             which GitHub labels mean "critical", when a PR is
                             blocked on the user. Pure predicates over ``raw``.
``projections``              Row -> widget-dict translation, composing the
                             three layers above. The public ``derive_*``
                             entry points live here.
``queries``                  The only module in the package that touches the
                             database: predicates, ordering, row caps.
===========================  ==================================================

What is deliberately NOT here: response envelopes, HTTP status policy, and
the live->seed fallback decision. Those are transport concerns and stay in
``api/v1/dashboard.py``. In particular the fallback policy must keep the DB
read *outside* its try/except so an infrastructure failure still surfaces as
a 500 rather than silently degrading to seed rows — fusing "fetch" and
"derive" into a single service call here would destroy that distinction.

Import from ``src.services.dashboard.<module>`` directly, so the layer a
call depends on is visible at the import.
"""
