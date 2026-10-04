# Screener usability implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement these tasks inline.

**Goal:** Improve readability, grouped navigation, responsive layouts and financial tables without changing trading or research calculations.

**Architecture:** Keep the existing static Python shell and vanilla JavaScript renderer. Update shared presentation styles and accessible navigation/table markup; preserve all snapshot inputs, sort/filter calculations and strategy engines.

**Tech stack:** Python HTML generator, native JavaScript, CSS, pytest.

**Spec:** User request in this chat: apply UI UX Pro Max to readability, navigation, mobile layouts and financial tables; trading logic unchanged. Retain dark/light green theme. Use a mobile disclosure menu (no overlay), 44px controls, 16px body text, tabular right-aligned numbers and sticky identifiers. Preserve deep links and browser history.

## Tasks
- [x] Add a labelled mobile navigation disclosure in research_view.py and event handling in research.js; verify routes, Escape, current-page semantics and keyboard focus.
- [x] Update research.css typography, touch targets, responsive grid/toolbar rules and contrast in both themes; verify 375px, tablet and desktop without page overflow.
- [x] Enhance shared table() with semantic column headers, numeric column alignment, keyboard scrolling, wrapping descriptions and sticky identifiers/headers; keep cell values unchanged. Preserve sort focus and announce direction.
- [x] Build docs/index.html; run pytest, JavaScript syntax and research math checks; manually verify filtering, sorting, navigation and entry evidence. Review diff for trading-logic isolation and obtain independent code review.

## Validation
Use the local app at port 8768. Compare rendered table values to the baseline, test mobile open/close and Escape, check hidden menu is excluded from focus, verify desktop navigation, light/dark screenshots, 375/768/1440px widths and keyboard table scrolling. Review all changed source paths; no engine, data provider, research_math.js or entrydesk changes. Publish only after checks pass.

## Completed verification
- 424 pytest tests and 2 subtests passed; 8 optional network tests deselected. Research math checks and JavaScript syntax passed.
- Browser: all 22 main navigation destinations had no outer-page overflow at 375px. Key research, market, news, portfolio and strategy pages also checked at 768px; overview at 1024px and screener at 1440px.
- Mobile menu opens/closes, Escape restores toggle focus, route selection closes navigation, aria-current identifies the route. Sorting retains button focus and announces direction. AAPL filtering returned the same recorded values as the baseline.
- Arrow-key horizontal scrolling measured 40px while the first column remained fixed at the wrapper edge. Wide journal first column corrected after independent review and measured 132px at phone width.
- Dark and light themes visually inspected. Minimum checked text contrast across base surfaces: dark 6.23:1, light 4.51:1.
- No trading engines, research_math.js, API collectors, strategy inputs or snapshot files changed by this UI work. Embedded original technical and breakout interfaces retain their own styling.
- Known pre-existing TradingView sandbox cookie errors remain outside this presentation change.

Ruling: Implemented inline on a dedicated branch in the existing checkout so the running local preview continues serving the updated build. User's standing instruction authorizes autonomous completion without confirmation.
