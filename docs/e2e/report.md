# Touchline end-to-end test report

**80 / 80 checks passed** in 153 s (fresh server, offline mode, demo match replayed at 45×).

Run it yourself: `cd backend && ../.venv/Scripts/python tests/e2e/run_e2e.py`

| Area | Check | Result | Detail |
|---|---|---|---|
| Platform | health | ✅ | {'ok': True, 'version': '1.0.0', 'llm': 'offline', 'hub': 'WebSocket', 'mode': 'local', 'season': True} |
| Platform | synthetic season loaded | ✅ |  |
| Data innovation | 20 fictional clubs | ✅ | 20 |
| Data innovation | season table after matchday 29 | ✅ | {'pos': 1, 'team': 'brk', 'p': 29, 'w': 16, 'd': 10, 'l': 3, 'gf': 63, 'ga': 41, 'pts': 58, 'form': 'DWDLW'} |
| Data innovation | 380-match synthetic season | ✅ | 380 |
| Render | JSON schema: event | ✅ |  |
| Render | JSON schema: overlay | ✅ |  |
| Render | JSON schema: insight | ✅ |  |
| Render | JSON schema: personalized | ✅ |  |
| Render | JSON schema: moment | ✅ |  |
| Render | JSON schema: recap | ✅ |  |
| Render | JSON schema: trace | ✅ |  |
| Render | JSON schema: fact | ✅ |  |
| Web | page / | ✅ | 200 |
| Web | page /live | ✅ | 200 |
| Web | page /overlay | ✅ | 200 |
| Web | page /control | ✅ | 200 |
| Web | page /recap | ✅ | 200 |
| Web | page /studio | ✅ | 200 |
| Web | 3D player model served | ✅ | 2160468 |
| Ingest | demo match events | ✅ | 1971 |
| Ingest | 5 Hz tracking frames | ✅ | 28835 |
| Interpret | facts registered | ✅ | 165 |
| Interpret | final score of scripted comeback | ✅ | [3, 2] |
| Personalise | 4 modes for one moment | ✅ |  |
| Personalise | modes are genuinely different | ✅ | ['¡Remontada completada! Jannik Krämer convierte una', '¡Remontada completada! ¡Gol de Jannik Krämer! 3-2.', 'Buenas noticias para el Northbank: ¡Remontada comp', 'Foco en Jannik Krämer: ¡Remontada completada! Jann'] |
| Explain | Guardian rejects corrupted draft | ✅ | ['Numbers not supported by cited facts: 3.42'] |
| Explain | Guardian approves grounded text | ✅ |  |
| Data innovation | scenario director builds a match from words | ✅ | {'events': 1897, 'frames': 27932, 'beats': 7} |
| Auto-eventing | ball detected from pixels | ✅ | 1.0 |
| Auto-eventing | players detected per frame | ✅ | 19.5 |
| Auto-eventing | passes detected and scored vs truth | ✅ | {'passes_truth': 8, 'passes_detected': 2, 'precision': 0.5, 'recall': 0.125, 'median_speed_error_kmh': 2.1} |
| Live | full match replayed | ✅ | 133s wall at 45x |
| Ingest | events streamed live | ✅ | 1971 |
| Render | tracking frames streamed | ✅ | 970 |
| Interpret | live stats snapshots | ✅ | 128 |
| Render | overlay cue templates | ✅ | ['lower_third', 'moment_card', 'momentum_bar', 'pass_rating', 'player_tag', 'score_bug', 'shot_speed', 'speed_badge', 'stat_compare', 'xg_popup'] |
| Render | cues timed (t_out > t_in) | ✅ | 249 |
| Player identification | name tags with player names | ✅ |  |
| Player identification | speed/distance badges on thresholds | ✅ |  |
| Explain | key moments detected | ✅ | {'yellow_card': 3, 'sprint': 3, 'goal': 5, 'big_chance': 5, 'pressure_shift': 2, 'momentum_swing': 1, 'milestone': 5, 'pass_of_match': 1, 'red_card': 2, 'phase': 2} |
| Explain | all 5 goals + red card detected | ✅ |  |
| Explainability | control vs chaos / pressing / momentum moments | ✅ | {'chaos_spike': 0, 'pressure_shift': 2, 'momentum_swing': 1} |
| Pass quality | pass of the match (difficulty rating) | ✅ |  |
| Pass quality | distance + difficulty on every pass | ✅ | 803 |
| Speed metrics | shot speed + xG on every shot | ✅ | [74, 76, 40, 92, 86, 84] |
| Speed metrics | ball speed on passes | ✅ |  |
| Ingest | pressure events | ✅ |  |
| Ingest | possession changes (interceptions/tackles) | ✅ |  |
| Explain | insights cite facts | ✅ | 145 |
| Personalise | fan:es receives own variants | ✅ | 29 · Amarilla para Yuto Fujiwara. |
| Multi-language | commentary in es | ✅ | 1' Amarilla para Yuto Fujiwara. |
| Personalise | analyst:en receives own variants | ✅ | 29 · Yuto Fujiwara is booked (Harbour yellow cards: 1). It limits how aggre |
| Multi-language | commentary in en | ✅ | 1' Yuto Fujiwara goes into the book. |
| Personalise | player:ja receives own variants | ✅ | 29 · Yuto Fujiwaraにイエロー。 |
| Multi-language | commentary in ja | ✅ | 1' Yuto Fujiwaraにイエロー。 |
| Personalise | club:fr receives own variants | ✅ | 29 · Bonne nouvelle pour Northbank : Yuto Fujiwara est averti (cartons jaun |
| Multi-language | commentary in fr | ✅ | 1' Jaune pour Yuto Fujiwara. |
| Personalise | fan:ar receives own variants | ✅ | 29 · إنذار لـYuto Fujiwara. |
| Multi-language | commentary in ar | ✅ | 1' إنذار لـYuto Fujiwara. |
| Personalise | player-focus mode tied to the followed player | ✅ | 29 |
| Explainability | tactical shift notes (Tactician) | ✅ | ['Harbour have pressed far more aggressively in the last 15 mi', 'Northbank have sped the game up: 7.1 passes/min compared wit'] |
| Narrative | half-time + full-time recaps | ✅ | ['Harbour lead Northbank at the break', 'Northbank complete a stunning comeback against Harbour'] |
| Narrative | player of the match with reason | ✅ | Renan Moraes: a 9.3 rating, 2 goals, 92% passing accuracy, 9.7 km covered. |
| Narrative | milestones / season context | ✅ | 5 |
| Multi-agent | all agents active | ✅ | ['explainer', 'guardian', 'memory', 'narrator', 'persona', 'producer', 'publisher', 'spotter', 'tactician'] |
| Multi-agent | Guardian caught injected wrong number | ✅ | Numbers not supported by cited facts: 18 |
| Multi-agent | Explainer rewrote after rejection | ✅ |  |
| Multi-agent | killed agent fell back, feed kept flowing | ✅ |  |
| Enterprise | human review paused and approved via Agent Framework | ✅ | ("GOAL — Reece Kettering (Harbour) 18'", 'published') |
| Enterprise | audit trail for every check | ✅ | 176 |
| Enterprise | per-agent telemetry (calls, latency, errors) | ✅ | {'calls': 242, 'tokens_in': 0, 'tokens_out': 0, 'cost_usd': 0.0, 'rejections': 1, 'retries': 1, 'fallbacks': 1} |
| Explain | citation resolves to a fact (+ source events) | ✅ | 3-2 |
| Watch party | join / presence / chat / reactions | ✅ | {'welcome': 1, 'presence': 2, 'tally': 2, 'chat': 2, 'react': 2, 'settled': 5} |
| Watch party | predictions settled by live goals | ✅ | [("Reece Kettering (Harbour) 18'", ['Ada']), ("Bram van Leer (Harbour) 37'", [])] |
| Ask | verified tool-based answer | ✅ | Fastest so far: Reece Kettering (Harbour) 33.2 km/h; Callum Thornton (Harbour) 33.1 km/h; Renan Pach |
| A2A | agent card published | ✅ |  |
| A2A | agent-to-agent call answered | ✅ | Expected goals: Northbank 3.49 from 22 shots, Harbour 0.99 from 8. Northbank have created the better |
| MCP | tools exposed | ✅ | ['list_matches', 'match_state', 'key_moments', 'events', 'player', 'fact', 'ask', 'agent_status', 'start_match', 'generate_match'] |
| MCP | match_state via MCP | ✅ | [3, 2] |
