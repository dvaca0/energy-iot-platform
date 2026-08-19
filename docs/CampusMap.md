# Campus Map

The geographic view of Universidad de Colima's electrical monitoring: real
OpenStreetMap building footprints with Energy IQ deployment and measurement
state drawn on top.

---

## What it is made of

| Layer | Where | Refreshed by |
|---|---|---|
| Building footprints | `backend/app/data/campus_map/geometry/campus-<id>.geojson` | `scripts/build_campus_geojson.py`, by hand |
| Campus property outline | the same file, under `properties.grounds` | the same script; `--grounds-only` refreshes it alone |
| Viewport configuration | `backend/app/data/campus_map/campuses.json` | edited by hand |
| Footprint → building join | `backend/app/data/campus_map/associations.json` | edited by hand |
| File loading and the join | `backend/app/services/campus_geometry.py` | — |
| Colour and freshness rules | `backend/app/services/campus_map_state.py` | — |
| The API | `backend/app/routers/campus_map.py` | — |
| The page | `frontend-src/src/pages/PageCampusMap.tsx` and `src/components/campusmap/` | — |

---

## Geometry inventory

Acquired from OpenStreetMap via the Overpass API and curated on **2026-08-19**
(Campus Central and Campus Coquimatlán were first curated 2026-08-18 and
re-curated on the 19th — see the note below). Every campus row in the
`campuses` table is listed; the map has geometry for all ten.

| Campus | DB id | Geometry | Boundary source | OSM feature | Footprints | Named | Confidence |
|---|---|---|---|---|---|---|---|
| El Naranjo | 1 | yes | explicit campus polygon | way 1322637475 *Universidad de Colima Campus El Naranjo* | 40 | 4 | high |
| San Pedrito | 2 | yes | explicit campus polygon | way 1323291611 *Universidad de Colima Campus San Pedrito* | 19 | 4 | high |
| Valle de las Garzas | 3 | yes | explicit campus polygon | way 1322653033 *Universidad de Colima Campus Valle de las Garzas* | 6 | 5 | high |
| Santiago | 4 | outline only | bachillerato site polygon | way 963566217 *Bachillerato Técnico 23 y 27* | 0 | 0 | high site, no traced buildings |
| El Colomo | 5 | yes | bachillerato site polygon | way 1487351797 *Bachillerato Tecnico No. 14* | 4 | 0 | high |
| Campus Tecomán | 6 | yes | union of five UdeC parcels | ways 634424356, 634424359, 1182771547, 1182771548, 1182771553 | 38 | 2 | high |
| Campus Central | 7 | yes | explicit campus polygons | ways 271818376 and 1151009203 *Universidad de Colima* | 140 | 62 | high |
| Campus Norte | 8 | yes | explicit campus polygon | way 346629240 *Universidad de Colima Campus Norte* | 7 | 5 | high |
| Campus Coquimatlán | 9 | yes | explicit campus polygon | way 569149333 *Universidad de Colima Campus Coquimatlán* | 65 | 18 | high |
| Campus Villa de Álvarez | 10 | yes | explicit campus polygon | way 564437580 *Universidad de Colima Campus Villa de Álvarez* | 30 | 5 | high |

**349 footprints in total.** The evidence for each identification is recorded
per campus in the `evidence` field of `campuses.json`; nothing reads it, it is
there so the dataset can be explained.

Three of these deserve a note.

**Santiago has a campus but no buildings.** OpenStreetMap has the site outline
for Bachillerato Técnico 23 y 27 and has traced nothing inside it. The four
polygons that a looser clip once admitted are houses 36–80 m outside the
fence, so they are excluded. The page draws the outline and says plainly that
OSM has no buildings there yet — which is the truth, and more useful than four
neighbours' houses shown as a campus.

**Santiago and El Colomo are bachilleratos, not faculty campuses.** Neither
OSM feature carries a UdeC operator tag, so the identification rests on the
university's own records: Bachillerato 14 (school key `06UCT0014V` — the `UC`
is Universidad de Colima) moved to El Colomo in 1988, and Bachilleratos 23 and
27 share one address in colonia Montebello, Santiago, on different shifts,
which is why OSM maps them as a single site. Both campus records have zero
`organizational_units`, consistent with a non-faculty site.

**Campus Tecomán has no single campus polygon.** Its grounds are the union of
five adjacent `amenity=university` parcels. Every such way inside the
acquisition bbox was checked individually and all five are UdeC; the untagged
selector is scoped by the bbox rather than trusted on its own.

### The 2026-08-19 re-curation

Campus Central and Campus Coquimatlán were re-curated even though they were
working, because the curation script's centroid was numerically broken and
their datasets had been clipped with it (see *Curation arithmetic* below).
Central gained 10 footprints and lost none; Coquimatlán gained 3 and lost one,
`way/1387045859` "Casa José Humberto Gutiérrez", a house 66 m outside the
campus that the old tolerance had admitted. The DIGESET association was
unaffected — it is keyed on the OSM id, which is the property this design
exists to have.

---

## Curation arithmetic

Two numerical rules the curation depends on, both of which were wrong at first
and are now covered by tests that fail on the old implementations.

**The shoelace centroid must be translated to a local origin.** Untranslated,
each term is `x0*y1 - x1*y0` where both products are about -1969 while their
difference for a 20 m building is about 1e-8. That is eleven of a double's
sixteen digits cancelling, and what survives is noise: the same Tecomán
footprint produced centroids 270 m apart depending only on how many decimals
its coordinates had been rounded to. Buildings were clipped against a point
that was not inside them. Subtracting the ring's first vertex first makes the
operands about 1e-4 and the error vanishes. The identical bug existed in the
frontend's `ringCentroid`, where it misplaced building labels.

**The clip tolerance measures distance to the boundary, not to its corners.**
A campus boundary has long straight runs with vertices only at their ends, so
measuring to vertices made a small tolerance behave like none at all. It is now
a true point-to-segment distance, and the tolerance for newly curated campuses
is **15 m** — enough for a building whose traced edge straddles the fence, not
enough to reach across a street. At the original 40 m, San Pedrito pulled in
Templo de San Pedro, a hospital and a kindergarten. Campus Central and
Coquimatlán keep 40 m, since that is the value their (now correct) curation was
verified at.

---

## Selection is physical, not electrical

The thing you select is an **OSM footprint**, identified by `osm_type/osm_id`.
Energy IQ buildings hang off that selection; they are never a precondition for
it. Most footprints on every campus have no association at all — 139 of Campus
Central's 140 — so gating selection on one would make almost the whole map dead
to the touch.

    selected footprint (osm_type/osm_id)
      └─ 0..N Energy IQ buildings
           └─ 0..1 operational deployment → node → readings

The panel therefore always has something to say. A footprint with no
association shows `SIN MONITOREO`, its OSM identity and building type, and
**no electrical section at all** — 0 kW is a measurement, and this building has
none.

"Sin identificar" and "sin monitoreo" answer different questions and are never
conflated: the first means nobody has named the outline, the second means
Energy IQ does not measure it.

### The click that did nothing

Fixed 2026-08-19. Hovering a polygon worked; clicking it appeared to do
nothing, and the panel never left its placeholder.

The cause was Leaflet event dispatch, not the association logic. `Map._initEvents`
registers the map itself under the map container:

    this._targets[stamp(this._container)] = this;

and `_findEventTargets` walks the DOM up from the clicked `<path>`, only
stopping *at* that container — so a click on a polygon resolves to
`[polygon, map]`, not `[polygon]`. `_fireDOMEvent` then fires **both**, bailing
out early only when the event was stopped or the target has
`bubblingMouseEvents === false` and the type is one of `_mouseEvents`. `Path`
defaults that option to `true`.

The map's own click handler clears the selection so that clicking bare map
deselects. The result: every building click set the selection and cleared it
again in the same dispatch, React batched the two updates, and the clear won.
Hover was unaffected because nothing competes for `mouseover`/`mouseout`.

The fix is one line — `bubblingMouseEvents: false` in the footprint path options
returned by `polygonStyle`. Clicking bare map still clears, because nothing
intercepts that click first. `tests/render-campus-map.tsx` models Leaflet's
dispatch loop against the real path options and fails without it.

---

## Overpass is a source, not a dependency

The footprints come from OpenStreetMap through the Overpass API, but nothing at
request time ever calls Overpass. `scripts/build_campus_geojson.py` runs by
hand, writes a `.geojson` file into the repository, and that file is what the
backend serves from then on. A page that had to reach a public API in Germany
before it could draw a building would go blank every time that API rate-limited
— which it does, readily, as the script's own retry loop attests.

Re-running the script overwrites a campus's geometry **wholesale**. It never
touches `associations.json`. That separation is the whole design: OSM geometry
can be refreshed at any time without disturbing a single curated association.

---

## OSM identity is not Energy IQ identity

`osm_type` + `osm_id` identify a physical outline. `buildings.id` identifies an
Energy IQ entity. The bridge between them is `associations.json`, and it is
maintained by a person.

**The OSM name is never a key.** Of the 130 footprints traced for Campus
Central, 60 have a name at all, and the ones that do carry a local nickname
rather than the institutional one — the DIGESET building is tagged `Servicios
Telemáticos` in OSM. Matching on the name would silently re-point a building's
energy data at a different polygon the day a mapper fixes a typo.

An association whose way no longer exists in OSM, or whose building has been
deleted from Energy IQ, is reported in the response as an
`orphan_associations` entry and shown on the page. It is not dropped: a
footprint that quietly stops being monitored looks exactly like one that never
was.

---

## Status colours

Set in `campus_map_state.derive_status` from four facts, each of which already
has an owner elsewhere in the platform.

| State | Colour | Means |
|---|---|---|
| `unregistered` | slate, low opacity | OSM knows this building; Energy IQ does not |
| `registered` | grey | An Energy IQ building with no deployment and no readings |
| `historical` | blue | Has measured before; nothing running now |
| `active_stale` | amber, hollow | Deployment active, no reading inside the telemetry window |
| `active_healthy` | green | Active, fresh, nothing open |
| `active_warning` | amber | Active and fresh, with an open `WARNING` or `ERROR` alert |
| `active_critical` | red | Active and fresh, with an open `CRITICAL` or `EMERGENCY` alert |

Selection draws the Energy IQ blue outline over whatever the state colour is.
The two carry different information and do not overwrite each other.

**Consumption magnitude is not one of the four facts.** A building drawing
400 kW because it runs a chiller is not in a worse state than one drawing 4 kW.
Magnitude gets its own map modes — POWER, ENERGY, COST, POWER FACTOR — on a
single-hue graduated ramp with no red end. Colouring high consumption red would
teach an operator that red means "busy", and then a real fault in red would be
ignored.

---

## Freshness

An `active` deployment is an *administrative* record: it says an operator
declared a campaign, not that data is arriving. The map asks the second question
separately, using the same five-minute window as
`app/services/deployment_scope.py`, and `active_stale` is its own state for it.

Folding stale into `active_healthy` would show a day-old number as current.
Folding it into `historical` would hide a campaign that is supposed to be
running, and therefore hide the fault. Every value in the detail panel is
labelled with the age of its reading; when the window has lapsed the block is
headed *Última medición* rather than *Medición actual*.

---

## Adding a campus

1. Find the campus id in the `campuses` table — the map never invents one.
2. Add an entry to `campuses.json` with a `bbox` (`[south, west, north, east]`)
   and `grounds_selectors`, the Overpass tag filters for the polygons that
   define the campus grounds. Buildings whose centroid falls outside them —
   the hotel, the church, the municipal offices that share a bounding box — are
   discarded.
3. Run the curation:

   ```bash
   python3 scripts/build_campus_geojson.py --campus <id>
   ```

4. Check the counts it prints — it reports how many footprints were kept and
   how many were discarded as outside the grounds — and commit the new
   `.geojson`. Then run the backend suite: it re-checks every shipped dataset
   against the containment and validity invariants.

To refresh only a campus outline, leaving its curated footprints untouched:

```bash
python3 scripts/build_campus_geojson.py --campus <id> --grounds-only
```

A campus with `"bbox": null`, or with no entry at all, is not an error: the API
reports `has_geometry: false` and the page shows the campus's summary with a
note instead of a map. A campus whose outline is mapped but whose buildings are
not — Santiago — renders the outline and says so.

The equivalent query, if you would rather explore it in Overpass Turbo first:

```
[out:json][timeout:25];
(
  way({{bbox}})["building"];
  relation({{bbox}})["building"];
);
out geom;
```

---

## Associating a building

Find the footprint. Hovering it on the map, or clicking it, shows its
`osm_type/osm_id` — the detail panel for an unassociated footprint prints
exactly the id you need. Then add an entry to `associations.json`:

```json
{
  "osm_type": "way",
  "osm_id": 625447870,
  "osm_name_at_curation": "Servicios Telemáticos",
  "energy_iq_building_id": 10,
  "campus_id": 7,
  "confidence": "surveyed",
  "note": "Why this footprint and not its neighbour."
}
```

`confidence` is `surveyed` when someone confirmed the panel is inside this
outline, and `inferred` when the match comes from the building's organisational
unit naming the dependency. It is recorded because a footprint is matched by a
human reading a map, not by a join.

The file is re-read whenever its modification time changes, so an edit takes
effect on the next request — no reload needed.

One footprint may carry several Energy IQ buildings; add one entry per
building. A physical building has more than one panel, and a re-instrumentation
creates a second `buildings` row for the same walls. The polygon takes the most
urgent of their states, so a healthy neighbour can never mask a critical one,
and the detail panel lists them all.

---

## Tests

```bash
cd backend && venv/bin/python3 -m tests.test_campus_map
cd frontend-src && npm test
```

The backend suite is hermetic — a throwaway SQLite database and throwaway
curation files — and also asserts against the curation actually shipped: every
association must resolve to a footprint that exists, and no geometry file may
carry an Energy IQ id. It drives one deployment through fresh, stale and closed
and requires three different states out of it.

The frontend suite covers the pure rules and the presentational components.
Leaflet needs a DOM and `renderToStaticMarkup` has none, which is why
`CampusEnergyMap` and `BuildingGeoJsonLayer` are the only files that import it —
they are covered by visual review on `:5175`.

---

## Attribution

Building geometry is © OpenStreetMap contributors, ODbL. The base tiles are
CARTO's dark basemap over the same data. Both notices appear in the map's
attribution control and in the legend. Do not remove either.
