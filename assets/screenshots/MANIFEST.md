# Screenshot manifest

Every image referenced by `README.md` and by `docs/`, what it must show, and
where it is used. Replace a file **in place, under the same name** and every
reference updates automatically — no document needs editing.

## Capture settings

| Setting | Value | Why |
|---|---|---|
| Viewport | **1600 × 1000** | Matches the existing set, so the gallery stays visually uniform. |
| Device pixel ratio | 2 (retina) if available | Text stays sharp when GitHub scales the image down. |
| Theme | **Dark** | The application ships dark-first; the README renders on both GitHub themes and dark shots read correctly on each. |
| Format | PNG | Lossless; these are UI shots, not photographs. |
| Chrome | Hide browser UI (F11 / headless) | Browser furniture dates the screenshot and adds nothing. |

Capture against the production frontend on `:5174`, or the staging frontend on
`:5175` when a change is not yet released.

> [!IMPORTANT]
> Before committing a screenshot, check it for anything that should not be
> public: real names, institutional email addresses beyond the generic
> `admin@ucol.mx`, tokens, internal hostnames, or public IP addresses. See
> [docs/Security.md](../../docs/Security.md).

## Application screens

Status legend — ✅ captured · ⬜ awaiting capture

| # | File | Screen | Must show | Status |
|---|---|---|---|---|
| 01 | `01-executive-dashboard.png` | Dashboard Ejecutivo | KPI row, cost-per-hour bars, tariff-period donut, weekly trend | ✅ |
| 02 | `02-live-monitoring.png` | Monitoreo en Vivo | Live node card: V, A, kW, PF, Hz, buffer depth | ✅ |
| 03 | `03-node-infrastructure.png` | Infraestructura | Node inventory, commission state, last sync | ✅ |
| 04 | `04-deployments.png` | Despliegues | Deployment list with lifecycle status and windows | ✅ |
| 05 | `05-smart-plugs.png` | Smart Plugs | Plug fleet, online state, per-plug power, assignment | ✅ |
| 06 | `06-ai-center.png` | Centro IA / Forecasting | Forecast curve, model, confidence basis | ✅ |
| 07 | `07-cost-analysis.png` | Análisis de Costo | GDMTH tariff-period breakdown, cost trend | ✅ |
| 08 | `08-data-explorer.png` | Explorador de Datos | Query builder, result table, export | ✅ |
| 09 | `09-data-mining.png` | Minería de Datos | Clustering / pattern output | ✅ |
| 10 | `10-reports.png` | Reportes | Generated report list and PDF preview | ✅ |
| 11 | `11-buildings.png` | Edificios | Building inventory with monitoring coverage | ✅ |
| 12 | `12-campus-map.png` | Mapa de Campus | Campus layout with node placement | ✅ |
| 13 | `13-settings.png` | Configuración | Thresholds, retention, AI toggles, tariff config | ✅ |
| 14 | `14-login.png` | Login | Authentication screen | ✅ |
| 15 | `15-deployment-selector.png` | Deployment selector | Active vs archived deployment switching | ✅ |

Screens 01–14 were captured on **2026-07-27**; screen 15 on **2026-08-04**.

## Hardware photographs

These cannot be produced from the server and are the one outstanding gap in the
visual set. Each is referenced by [docs/Hardware.md](../../docs/Hardware.md);
until a file exists the reference degrades to alt text.

| # | File | Must show | Status |
|---|---|---|---|
| H1 | `hardware/01-node-enclosure.jpg` | A complete node in its enclosure, lid off — Pi, ADC board, terminal blocks | ⬜ |
| H2 | `hardware/02-panel-installation.jpg` | The node mounted at a live electrical panel, CT clamps around the conductors | ⬜ |
| H3 | `hardware/03-ct-clamps.jpg` | Current transformer clamps in close-up, showing model markings | ⬜ |
| H4 | `hardware/04-adc-wiring.jpg` | ADS1256 board wiring detail — SPI header, analogue inputs, burden resistors | ⬜ |
| H5 | `hardware/05-smart-plug.jpg` | A Shelly Plug US Gen4 in service on a monitored outlet | ⬜ |
| H6 | `hardware/06-bench-setup.jpg` | The bench rig used for calibration and bring-up | ⬜ |

**Photography guidance.** Landscape, 3:2, minimum 2000 px on the long edge, JPEG
quality ≈ 85. Diffuse light, no direct flash. Mask or avoid: serial numbers,
MAC address labels, Wi-Fi credentials on stickers, room numbers, and anything
identifying a person.

> [!CAUTION]
> Photograph H2 involves a live panel. Do not open an energised enclosure to
> stage a photograph. Use an existing maintenance window and follow the site's
> electrical safety procedure.
