# Phase 1 prototype

`2026-06-phase1-prototype.html` is the single-file React 18 prototype that the
current application was migrated from, on **2026-06-14** — the first commit in
this repository's history is literally *"Phase 1 - Claude dashboard successfully
migrated to React"*.

It is kept for provenance. It is **not** part of the application:

- Nothing imports or links to it.
- It loads React from a CDN at runtime, so it does not work offline and is not
  covered by the project's dependency auditing.
- It has not been maintained since June 2026.

It previously sat in `frontend/public/`, which meant Vite copied it into `dist`
and the production static server published it at
`/energy-platform-professional.html` — an unmaintained, unreferenced page on the
same origin as the live dashboard. It was moved here so it stops being served
while remaining readable.

To view it, open the file directly in a browser.
