# Energy IQ — brand assets

The identity is deliberately plain: an instrument panel, not a consumer product.
Blue carries the platform, amber carries anything a human must look at, and
everything else is neutral so that measured data is the only thing with colour.

## Files

| File | Use |
|---|---|
| `logo.svg` | Full lockup — mark plus wordmark. Uses `currentColor` for text, so it adapts to light and dark automatically. |
| `logo-mark.svg` | Square mark alone. Use where the wordmark would be under ~120 px wide. |
| `favicon.svg` | Simplified mark for tab icons — the trace is dropped because it disappears below 32 px. |
| `hero.svg` | README banner, 1280 × 360. |
| `social-preview.png` | GitHub social preview, 1280 × 640. Upload under *Settings → General → Social preview* (GitHub does not accept SVG here). |
| `logo-mark-512.png`, `logo-mark-256.png` | Raster mark for contexts without SVG support. |
| `favicon-64.png`, `favicon-32.png`, `apple-touch-icon.png` | Raster icon sizes. |
| `generate_raster.py` | Regenerates every PNG from the same drawing code. |

SVG is the source of truth. Regenerate the rasters after any change to the mark:

```bash
backend/venv/bin/python3 assets/branding/generate_raster.py
```

## Colour palette

| Role | Token | Hex | Notes |
|---|---|---|---|
| Primary | Blue 500 | `#3B82F6` | Interactive elements, the primary data series. |
| Primary deep | Blue 700 | `#1D4ED8` | Gradient end, pressed states. |
| Primary pale | Blue 200 | `#BFDBFE` | Traces and secondary marks on dark. |
| Attention | Amber 500 | `#F59E0B` | Peak-tariff periods, values needing a human decision. |
| Healthy | Green 500 | `#22C55E` | Node online, rule passing, resolved alert. |
| Fault | Red 500 | `#EF4444` | Firing alert, offline node, failed sync. |
| Canvas | Ink | `#0B1120` | Application background. |
| Surface | Ink mid | `#111C33` | Cards and panels. |
| Text primary | Slate 100 | `#F1F5F9` | |
| Text secondary | Slate 400 | `#94A3B8` | |
| Text muted | Slate 500 | `#64748B` | Labels, axis ticks. |

Amber and red are never used decoratively. If something is amber on a dashboard
it is because a tariff period or a threshold made it so.

**Contrast.** Slate 100 on Ink is ≈ 16.8:1 and Slate 400 on Ink ≈ 6.9:1, both
clearing WCAG AA for body text. Slate 500 on Ink is ≈ 4.1:1 — acceptable for
non-essential labels at ≥ 14 px semibold, but never for values a reader must
act on.

## Typography

| Context | Face | Fallback stack |
|---|---|---|
| UI and headings | **Inter** | `Inter, "Segoe UI", system-ui, -apple-system, sans-serif` |
| Measured values | **Inter**, tabular numerals (`font-variant-numeric: tabular-nums`) | as above |
| Code and identifiers | **JetBrains Mono** | `"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace` |

Tabular numerals are not a stylistic preference. Live readings update several
times per second and proportional digits make the whole row twitch on every
refresh.

The raster assets are drawn with **DejaVu Sans**, the only font installed on the
build host. If you regenerate them somewhere with Inter available, point
`BOLD`/`BOOK` in `generate_raster.py` at it for a closer match to the UI.

## Usage

- Keep clear space of at least half the mark's height on every side.
- Do not recolour the mark. On a background that clashes, use the mark on its
  own blue tile — that is what the tile is for.
- Do not stretch, rotate, add effects, or place the mark on a busy photograph.
- The wordmark is "Energy IQ". "UCOL Platform" is a descriptor and may be
  dropped at small sizes.
