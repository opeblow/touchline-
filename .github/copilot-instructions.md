# Copilot instructions

Follow [AGENTS.md](../AGENTS.md) (rules, stack, contracts) and [DESIGN.md](../DESIGN.md) (UI).
Key rules:
- LLM agents never produce numbers. Stats come from `services/stats`, and agents cite `fact_id`s.
- Every agent output passes the Guardian.
- Synthetic, fictional data only. No real clubs, players or league marks.
- Check new features against [CRITERIA.md](../CRITERIA.md).
