---
mode: agent
description: Add a new key-moment type end to end (detector, facts, templates in 6 languages, tests).
---

Add a new moment type to Touchline: ${input:moment_type} (${input:description}).

1. Add the enum value to `MomentType` in `backend/touchline/models.py`.
2. Detect it in `backend/touchline/intel/moments.py`. Create every number with `stats.fact(...)` and set a cool-down.
3. Add `head`, `why` and `fan` templates for **all six languages** in `backend/touchline/agents/templates.py`, and labels for any new fact kinds in `FACT_LABELS`.
4. Add a label in `web/lib/format.ts` → `MOMENT_LABEL`.
5. Run `pytest -q backend/tests`. `test_every_template_is_grounded` must pass, which means every number in every language is Guardian-approved.

Rules: never write a number that is not a fact; fictional names only. Follow AGENTS.md.
