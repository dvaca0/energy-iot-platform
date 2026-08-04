# Frontend — Energy IQ dashboard

React 19 + TypeScript + Vite. Thirteen screens over the platform: executive
dashboard, campus map, buildings, deployments, live monitoring, cost analysis,
AI centre, data mining, data explorer, reports, infrastructure, smart plugs and
settings.

**Full documentation: [`docs/Frontend.md`](../docs/Frontend.md).**

## Commands

```bash
npm ci
npm run dev      # Vite dev server with HMR
npm run build    # tsc -b && vite build  →  dist/
npm run lint
```

## Deployment is the build

`static_server.py` serves `dist/` on port **5174** with `Cache-Control:
no-store`, so a completed `npm run build` **is** the release — no service
restart and no cache purge. See [`docs/Deployment.md`](../docs/Deployment.md).

> [!IMPORTANT]
> The deployment server carries a second, byte-identical checkout at
> `frontend-src/`, served on **:5175** by `static_server_test.py`, used to
> review a change before repeating it in production. The two directories differ
> only by name, so **confirm your path before building.** Only this tree is
> tracked in git; `frontend-src/` is a deployment artefact of that host.

## Notes for anyone reading the source

- **No CSS framework.** Styling is inline `style={{}}` objects driven by token
  objects in `src/styles/theme.ts`, `src/components/smartplugs/styles.ts` and a
  `T` object in `src/pages/PageSettings.jsx`. `src/index.css` holds the CSS
  custom properties those mirror.
- **`src/App.tsx` is ~2.4k lines** and holds most screens.
  `src/components/smartplugs/` is the one fully extracted feature module and is
  the pattern the rest should follow.
- **Dead code:** `src/app.css`, `src/components/common.tsx`,
  `src/components/ui/*` and `src/pages/CostAnalytics.tsx` are not reachable from
  `main.tsx`. Do not treat them as examples of current style.
- **State is local React state plus polling** — 3 s on live screens, 30 s on
  dashboards. No Redux, no React Query, no WebSocket. Every request goes through
  `src/services/api.ts`.
- **The interface is Spanish**; the code and comments are English.

## Known gaps

The app has **no test suite**, and ESLint reports 36 pre-existing findings in
`src/` (a `@ts-nocheck`, several `any`s, components declared during render). CI
reports them without failing the build — see
[`docs/Frontend.md`](../docs/Frontend.md#known-gaps).
