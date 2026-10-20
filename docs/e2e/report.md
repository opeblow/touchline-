# Touchline end-to-end test report

**80 / 80 checks passed** in 162 s (fresh server, offline mode, demo match replayed at 45×).

Run it yourself: `cd backend && ../.venv/Scripts/python tests/e2e/run_e2e.py`

| Area | Check | Result | Detail |
|---|---|---|---|
| Platform | health | PASS | {'ok': True, 'version': '1.0.0', 'llm': 'offline', 'hub': 'WebSocket', 'mode': 'local', 'season': True} |
| Platform | synthetic season loaded | PASS |  |
| Data innovation | 20 fictional clubs | PASS | 20 |
| Data innovation | season table after matchday 29 | PASS | {'pos': 1, 'team': 'brk', 'p': 29, 'w': 16, 'd': 10, 'l': 3, 'gf': 63, 'ga': 41, 'pts': 58, 'form': 'DWDLW'} |
| Data innovation | 380-match synthetic season | PASS | 380 |
| Render | JSON schema: event | PASS |  |
| Render | JSON schema: overlay | PASS |  |
| Render | JSON schema: insight | PASS |  |
| Render | JSON schema: personalized | PASS |  |
| Render | JSON schema: moment | PASS |  |
| Render | JSON schema: recap | PASS |  |
| Render | JSON schema: trace | PASS |  |
| Render | JSON schema: fact | PASS |  |
| Web | page / | PASS | 200 |
| Web | page /live | PASS | 200 |
| Web | page /overlay | PASS | 200 |
| Web | page /control | PASS | 200 |
| Web | page /recap | PASS | 200 |
| Web | page /studio | PASS | 200 |
| Web | 3D player model served | PASS | 2160468 |
| Ingest | demo match events | PASS | 1971 |
| Ingest | 5 Hz tracking frames | PASS | 28835 |
| Interpret | facts registered | PASS | 165 |
| Interpret | final score of scripted comeback | PASS | [3, 2] |
| Personalise | 4 modes for one moment | PASS |  |
| Personalise | modes are genuinely different | PASS | ['¡Remontada completada! Jannik Krämer convierte una', '¡Remontada completada! ¡Gol de Jannik Krämer! 3-2.', 'Buenas noticias para el Northbank: ¡Remontada comp', 'Foco en Jannik Krämer: ¡Remontada completada! Jann'] |
| Explain | Guardian rejects corrupted draft | PASS | ['Numbers not supported by cited facts: 3.42'] |
| Explain | Guardian approves grounded text | PASS |  |
| Data innovation | scenario director builds a match from words | PASS | {'events': 1897, 'frames': 27932, 'beats': 7} |
| Auto-eventing | ball detected from pixels | PASS | 1.0 |
| Auto-eventing | players detected per frame | PASS | 19.5 |
| Auto-eventing | passes detected and scored vs truth | PASS | {'passes_truth': 8, 'passes_detected': 2, 'precision': 0.5, 'recall': 0.125, 'median_speed_error_kmh': 2.1} |
| Live | full match replayed | PASS | 132s wall at 45x |
| Ingest | events streamed live | PASS | 1971 |
| Render | tracking frames streamed | PASS | 968 |
| Interpret | live stats snapshots | PASS | 128 |
| Render | overlay cue templates | PASS | ['lower_third', 'moment_card', 'momentum_bar', 'pass_rating', 'player_tag', 'score_bug', 'shot_speed', 'speed_badge', 'stat_compare', 'xg_popup'] |
| Render | cues timed (t_out > t_in) | PASS | 249 |
| Player identification | name tags with player names | PASS |  |
| Player identification | speed/distance badges on thresholds | PASS |  |
| Explain | key moments detected | PASS | {'yellow_card': 3, 'sprint': 3, 'goal': 5, 'big_chance': 5, 'pressure_shift': 2, 'momentum_swing': 1, 'milestone': 5, 'pass_of_match': 1, 'red_card': 2, 'phase': 2} |
| Explain | all 5 goals + red card detected | PASS |  |
| Explainability | control vs chaos / pressing / momentum moments | PASS | {'chaos_spike': 0, 'pressure_shift': 2, 'momentum_swing': 1} |
| Pass quality | pass of the match (difficulty rating) | PASS |  |
| Pass quality | distance + difficulty on every pass | PASS | 803 |
| Speed metrics | shot speed + xG on every shot | PASS | [74, 76, 40, 92, 86, 84] |
| Speed metrics | ball speed on passes | PASS |  |
| Ingest | pressure events | PASS |  |
| Ingest | possession changes (interceptions/tackles) | PASS |  |
| Explain | insights cite facts | PASS | 145 |
| Personalise | fan:es receives own variants | PASS | 29 · Amarilla para Yuto Fujiwara. |
| Multi-language | commentary in es | PASS | 1' Amarilla para Yuto Fujiwara. |
| Personalise | analyst:en receives own variants | PASS | 29 · Yuto Fujiwara is booked (Harbour yellow cards: 1). It limits how aggre |
| Multi-language | commentary in en | PASS | 1' Yuto Fujiwara goes into the book. |
| Personalise | player:ja receives own variants | PASS | 29 · Yuto Fujiwaraにイエロー。 |
| Multi-language | commentary in ja | PASS | 1' Yuto Fujiwaraにイエロー。 |
| Personalise | club:fr receives own variants | PASS | 29 · Bonne nouvelle pour Northbank : Yuto Fujiwara est averti (cartons jaun |
| Multi-language | commentary in fr | PASS | 1' Jaune pour Yuto Fujiwara. |
| Personalise | fan:ar receives own variants | PASS | 29 · إنذار لـYuto Fujiwara. |
| Multi-language | commentary in ar | PASS | 1' إنذار لـYuto Fujiwara. |
| Personalise | player-focus mode tied to the followed player | PASS | 29 |
| Explainability | tactical shift notes (Tactician) | PASS | ['Harbour have pressed far more aggressively in the last 15 mi', 'Northbank have sped the game up: 7.1 passes/min compared wit'] |
| Narrative | half-time + full-time recaps | PASS | ['Harbour lead Northbank at the break', 'Northbank complete a stunning comeback against Harbour'] |
| Narrative | player of the match with reason | PASS | Renan Moraes: a 9.3 rating, 2 goals, 92% passing accuracy, 9.7 km covered. |
| Narrative | milestones / season context | PASS | 5 |
| Multi-agent | all agents active | PASS | ['explainer', 'guardian', 'memory', 'narrator', 'persona', 'producer', 'publisher', 'spotter', 'tactician'] |
| Multi-agent | Guardian caught injected wrong number | PASS | Numbers not supported by cited facts: 18 |
| Multi-agent | Explainer rewrote after rejection | PASS |  |
| Multi-agent | killed agent fell back, feed kept flowing | PASS |  |
| Enterprise | human review paused and approved via Agent Framework | PASS | ("GOAL — Reece Kettering (Harbour) 18'", 'published') |
| Enterprise | audit trail for every check | PASS | 176 |
| Enterprise | per-agent telemetry (calls, latency, errors) | PASS | {'calls': 242, 'tokens_in': 0, 'tokens_out': 0, 'cost_usd': 0.0, 'rejections': 1, 'retries': 1, 'fallbacks': 1} |
| Explain | citation resolves to a fact (+ source events) | PASS | 3-2 |
| Watch party | join / presence / chat / reactions | PASS | {'welcome': 1, 'presence': 2, 'tally': 2, 'chat': 2, 'react': 2, 'settled': 5} |
| Watch party | predictions settled by live goals | PASS | [("Reece Kettering (Harbour) 18'", ['Ada']), ("Bram van Leer (Harbour) 37'", [])] |
| Ask | verified tool-based answer | PASS | Fastest so far: Reece Kettering (Harbour) 33.2 km/h; Callum Thornton (Harbour) 33.1 km/h; Renan Pach |
| A2A | agent card published | PASS |  |
| A2A | agent-to-agent call answered | PASS | Expected goals: Northbank 3.49 from 22 shots, Harbour 0.99 from 8. Northbank have created the better |
| MCP | tools exposed | PASS | ['list_matches', 'match_state', 'key_moments', 'events', 'player', 'fact', 'ask', 'agent_status', 'start_match', 'generate_match'] |
| MCP | match_state via MCP | PASS | [3, 2] |
