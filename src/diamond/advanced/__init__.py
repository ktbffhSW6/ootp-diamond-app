"""Modern advanced statistics derived from OOTP at-bat data + dump rollups.

Five tiers organized by source:
  - contact:      Tier 1 — modern contact-quality (Hard Hit %, Barrel %, etc.)
  - situational:  Tier 2 — RE24, RISP, leverage, by-inning, vs-pitcher splits
  - sabermetric:  Tier 3 — wRC, wRC+, wRAA, custom WAR (needs league constants)
  - defensive:    Tier 4 — Range Factor, Catcher Framing+, OF Assist Rate
  - approach:     Tier 5 — terminal-count approach metrics

Run `diamond advanced` to produce a per-player advanced-stats report.
"""
