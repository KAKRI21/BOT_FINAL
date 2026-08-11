# Graph Report - .  (2026-07-03)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 54 nodes · 67 edges · 14 communities (9 shown, 5 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 3 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_BotRdvPermis|BotRdvPermis]]
- [[_COMMUNITY_main.py|main.py]]
- [[_COMMUNITY_bot.py|bot.py]]
- [[_COMMUNITY_RDVPermis Bot System|RDVPermis Bot System]]
- [[_COMMUNITY_notifier.py|notifier.py]]
- [[_COMMUNITY_._scan_centre_unique|._scan_centre_unique]]
- [[_COMMUNITY_test_ban.py|test_ban.py]]
- [[_COMMUNITY_Bot Settings|Bot Settings]]
- [[_COMMUNITY_Notification Settings|Notification Settings]]
- [[_COMMUNITY_aiohttp Dependency|aiohttp Dependency]]

## God Nodes (most connected - your core abstractions)
1. `BotRdvPermis` - 19 edges
2. `main()` - 7 edges
3. `notifier()` - 5 edges
4. `_filtrer_creneaux()` - 4 edges
5. `sauvegarder_session()` - 3 edges
6. `_filtre_heure()` - 3 edges
7. `apply_overrides()` - 3 edges
8. `run()` - 3 edges
9. `setup_logging()` - 2 edges
10. `load_config()` - 2 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `BotRdvPermis`  [EXTRACTED]
  main.py → bot.py
- `run()` --calls--> `BotRdvPermis`  [EXTRACTED]
  main.py → bot.py
- `Playwright Dependency` --conceptually_related_to--> `Chrome Remote Debugging Command`  [INFERRED]
  requirements.txt → cmd.txt
- `PyYAML Dependency` --references--> `Search Configuration`  [INFERRED]
  requirements.txt → config.yaml
- `main()` --calls--> `sauvegarder_session()`  [EXTRACTED]
  main.py → bot.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Bot Configuration and Execution** — cmd_chrome_command, config_search, config_bot, requirements_playwright [INFERRED 0.85]

## Communities (14 total, 5 thin omitted)

### Community 1 - "main.py"
Cohesion: 0.43
Nodes (7): sauvegarder_session(), apply_overrides(), load_config(), main(), Applique les arguments CLI par-dessus config.yaml, run(), setup_logging()

### Community 2 - "bot.py"
Cohesion: 0.40
Nodes (5): _filtre_heure(), _filtrer_creneaux(), bot.py — Bot RdvPermis V5 FINAL — Version complète avec toutes les améliorations, Vérifie si un créneau est dans la plage horaire configurée., Filtre et trie les créneaux selon la config :       - heure_min/max : exclut les

### Community 3 - "RDVPermis Bot System"
Cohesion: 0.33
Nodes (6): Chrome Remote Debugging Command, Reservation Configuration, Search Configuration, RDVPermis Bot System, Playwright Dependency, PyYAML Dependency

### Community 4 - "notifier.py"
Cohesion: 0.53
Nodes (5): bip_sonore(), envoyer_email(), envoyer_telegram(), notifier(), notifier.py — Notifications (son, Telegram, Email)

### Community 6 - "test_ban.py"
Cohesion: 0.67
Nodes (3): charger_cookies(), test_ban.py — Vérifie si ton IP est bannie par la plateforme permisdeconduire.go, run()

## Knowledge Gaps
- **6 isolated node(s):** `Reservation Configuration`, `Bot Settings`, `Notification Settings`, `Playwright Dependency`, `aiohttp Dependency` (+1 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BotRdvPermis` connect `BotRdvPermis` to `main.py`, `bot.py`, `._scan_centre_unique`, `.boucle`, `.se_connecter`?**
  _High betweenness centrality (0.303) - this node is a cross-community bridge._
- **Why does `notifier()` connect `notifier.py` to `bot.py`?**
  _High betweenness centrality (0.114) - this node is a cross-community bridge._
- **Why does `main()` connect `main.py` to `BotRdvPermis`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **What connects `bot.py — Bot RdvPermis V5 FINAL — Version complète avec toutes les améliorations`, `Vérifie si un créneau est dans la plage horaire configurée.`, `Filtre et trie les créneaux selon la config :       - heure_min/max : exclut les` to the rest of the system?**
  _13 weakly-connected nodes found - possible documentation gaps or missing edges._