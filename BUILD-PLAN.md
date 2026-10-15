# Drape — Clothing Creator for Blender
*Build plan. Working title "Drape". Target: Blender 5.2 extension. Sister tool to Wisp (hair); shares its `core/` module.*

**Vision:** select a body → paint or draw where the garment goes → generate a fitted, non-destructive garment → style seams/hems/details → simulate or export. Works on Character Creator (FBX) and VRoid (VRM) bodies. Same philosophy as Wisp: draw sparse structure, the system amplifies it.

**Golden rule:** every phase ends installable and testable. Defaults over options.

**Dependency:** Wisp Phases 0–2 build the shared core (surface drawing, region masks, GN builders, import normalization). Start Drape after those exist, then extract `core/` into a shared module both tools import.

---

## Phase 0 — Scaffold (½ day) ✅ *done 2026-10-14 (v0.1.0)*
- [x] Extension package `drape/` (manifest + `build_drape.py` → `dist/drape-<ver>.zip`, copied from Wisp)
- [x] Vendored a copy of Wisp's `core/` at Wisp commit f49647b — body-relevant modules only (geometry, nodes, rig, scalp_detect, motion); the hair-only ones stay in Wisp. Fixes here go back to Wisp until the two are merged into one shared module
- [x] Installs and shows an empty "Drape" N-panel in 5.2 — verified headless in Blender 5.2.0 LTS with a throwaway profile (installs, enables, all core modules import, unregisters cleanly). Not yet eyeballed in the live UI
- [x] Licence: GPL-3.0-or-later, matching Wisp and the Blender Extensions platform rule (switched from the repo's initial MIT on 2026-10-14)

## Phase 1 — Body Setup ✅ *core done 2026-10-14 (v0.2.0)*
- [x] Import normalization: CC / VRoid / generic body detection (`core/rig.py`) — **Set Up Body** finds armature, pipeline and body mesh from any selected part (jeans, hair, body)
- [x] Body region masks (`core/body_regions.py`): main bones classified by name (CC, VRoid, Mixamo, Rigify keywords), every other bone (twist/share/finger/toe, VRoid `J_Sec_*`/`J_Adj_*`) inherits from its nearest classified ancestor — hierarchy beats the name for side (VRoid ships `J_Sec_R_TopsUpperLegBack_end_01` under the *left* thigh). Each vertex → part with the most skin weight (16 parts with L/R) → 8 exclusive regions: Head, Neck, Torso, Hips, Arms, Hands, Legs, Feet
- [x] Storage: `drape_part` / `drape_region` int point attributes (authoritative) mirrored to `DRAPE_REGION_*` vertex groups; `Drape Regions` colour attribute + **Show Regions** toggle (Solid → Attribute)
- [x] Paint refine: pick a region → Refine by Painting → Finish Painting. Painted-in verts move to the region; erased verts go to the next region by skin weight, or (if they only had weight there) to their neighbours' majority region. Every vertex stays in exactly one region
- [x] **Done when** verified live in Blender 5.2.0: Nova (CC, 14 164 verts) and Wei Li (VRoid, 7 909) each set up in one click, < 0.1 s, zero unassigned verts, clean front/back splits
- [ ] Surface-snapped curve drawing — moved to Phase 2 (boundary curves come from region/coverage edges first; free drawing only needed for necklines/hems later). Wisp's Phase 2 hasn't built it either
- [ ] Panel draw verified by code against a stand-in layout, not yet clicked in the live UI
- **Found:** VRoid exports bake the outfit into `Body` (Wei Li's T-shirt/shorts/shoes are body geometry, with `J_Sec_*Tops*` physics bones). Regions still split correctly, but Drape garments would sit over the baked clothes. Need a nude VRoid export (or a "strip baked outfit" step) before Phase 2 testing on VRoid
- **Noted:** Wei Li's hips edge is jagged along the baked shirt hem — fine as an auto-guess; Phase 2 smooths coverage borders anyway

## Phase 2 — Garment Generation MVP  → *first shippable* ✅ *core done 2026-10-14 (v0.3.0)*
The core trick: paint coverage → get a garment. Non-destructive throughout.

- [x] Paint garment coverage on body (mask) → GN generates an offset shell (`core/garment.py`, group "Drape Garment Shell", v11). The garment is its own object at the world origin reading the **evaluated** body (posed) in world metres, so it follows animation and updates live while the coverage is painted. Pipeline: body mesh only → weld seams → soften coverage → keep a band → subdivide → **true iso-cut** (points where coverage crosses 0.5 on each edge; uncovered verts snap to them; snapped duplicates merged) → smooth the edge as a line → **Looseness** (surface relax, faded to 0 within 4 cm of the edges) → collide (push out to ≥ Offset) → Solidify (Thickness, outward, no even-offset, clamped)
- [x] Coverage is **geometric**, not per-vertex 0/1 (`core/coverage.py`): a 0..1 value fading over 3 cm across the real cut (a plane along the limb bone, a hem height), so cuts are straight whatever the mesh's triangles look like
- [x] Garment templates: T-Shirt, Tank Top, Long Sleeve, Shorts, Pants, Socks. Lengths along bones (sleeve 0..2 = shoulder→elbow→wrist, leg 0..2 = hip→knee→ankle, sock height), hem down the hips region, rise up the torso. Per-template fit + colour defaults
- [x] Toon + simple PBR fabric materials (`core/fabric.py`), switchable live; Toon = Shader to RGB two-tone (EEVEE only)
- [x] Panel: template → Add; per garment Shape sliders (rewrite coverage live), Paint Coverage / Finish / Reset to Template, Fit (Offset, Looseness, Thickness, Edge Smoothing, Resolution), Look (Fabric/Toon, colour). Older shell groups auto-upgrade on load (values carried by name)
- [x] **Done when** verified live in Blender 5.2: T-shirt + shorts on the nude VRoid (Body.001) and on Nova (CC) in **two clicks each, ~0.6 s**; painting a forearm into the shirt's coverage grew the sleeve immediately (13 356 → 16 178 verts); raising the arm 40° carried the garment. Tank/Long Sleeve/Pants/Socks generate on both bodies (checked numerically, not by eye)
- [ ] Boundary curves as editable objects (necklines, hems) — the shell already has clean edges from the iso-cut; editable curves move to Phase 4 with seams/hems trim
- [ ] Skirt — a body-following shell can't make one (it would split between the legs); it needs a cone/tube built from the waist and Phase 3 cloth sim
- [ ] Panel checked by code against a stand-in layout, not clicked in the live UI
- **Hard-won (VRoid):** (1) bodies duplicate every UV/material seam vertex → weld first or seams open as holes and fake hems; (2) long thin thigh triangles → 0/1 coverage cuts as teeth, hence geometric coverage + iso-cut; (3) the VRM add-on's **MToon Outline** modifier makes the evaluated body carry an outline *instance* → take only the mesh component, or it rides through as a floating copy; (4) Looseness on an open tube curls the end inward → fade it near edges; (5) Solidify even-offset spikes at tight folds and on zero-area faces
- **Hard-won (GN):** Blur Attribute's Weight doesn't restrict averaging to weighted neighbours, so border-only smoothing on a mesh doesn't work — smooth the border as curves instead

## Phase 3 — Fit & Simulation ✅ *core done 2026-10-14 (v0.4.0)*
- [x] Fit with adjustable tightness: **Fit** dropdown (Skin-tight / Fitted / Relaxed / Loose) sets Offset + Looseness together (`TIGHTNESS_FIT` in `core/coverage.py`); the shell's collide pass already keeps cloth ≥ Offset off the skin. Templates start from a preset
- [x] **Skirt** (`core/skirt.py`): a real mesh, since a body shell would split between the legs. A-line tube: waist ring fitted to the body (arms/hands/head excluded from the outline — they hang beside the hips in an A-pose), flare per metre of drop, every ring pushed clear of hips/buttocks/thighs and never narrowing, bone-parented to the pelvis (keeps world placement). Sliders: Length (0 hip … 1 knee … 2 ankle), Flare, Waist; changing one rebuilds the mesh and drops a stale drape
- [x] Cloth sim presets (`core/sim.py`): Drape (cotton, 60 f), Settle (denim, 40 f), Windy (silk, 120 f + a wind field per body, kept while any of that body's garments uses Windy). Pins: skirt top 2 rings; shells get a body pin map (`DRAPE_PIN_<garment>`: shoulders for tops, waistband for bottoms, all for socks) that the shell copies into the garment's `Drape_Pin` group (shell v12 `Pin` input). Body collides through a hidden GN proxy (`Drape_Collider_<body>`, Collision modifier) — the character object is never touched; hidden-by-eye still collides
- [x] Bake to shape key: **Drape** on a skirt simulates then keeps the last frame as shape key "Drape Settled" (cloth switched off; base mesh intact; still follows the pelvis). Release Drape / Remove Cloth undo it. Shells (no mesh of their own) keep the baked cache instead; **Whole Animation** simulates over the scene range
- [x] **Done when** verified live: Add → Skirt → **Drape** on Nova (CC) and the VRoid: believable folds, resting on hips and legs without passing through, ~4.6 s for 60 frames; drape kept at frame 1 and follows a 30° hip rotation. Windy and a T-shirt shell sim (61 f, shoulders pinned) also run
- [ ] Cuffs aren't pinned (they hang); per-garment pin painting not exposed in the UI yet
- [ ] Shell sims are slow (~13k verts; quality 5, still well over a minute for 60 f on the T-shirt) — consider simulating a low-res proxy and binding the shell to it (Surface Deform) in a later pass
- [ ] Layering: a skirt's waistband intersects a shirt hem (Phase 4)
- [ ] Panel checked by code against a stand-in layout, not clicked in the live UI
- **Hard-won:** an empty made with `bpy.data.objects.new(name, None)` has no force field (`obj.field` is None) — make wind with `bpy.ops.object.effector_add`; `ptcache.bake` needs a `point_cache` context override; Keep Drape marks the cache "outdated" (the shape key changes the mesh), which is expected

## Phase 4 — Details & Tailoring ✅ *core done 2026-10-14 (v0.5.0)*
Where garments stop looking like shells.

- [x] **Layering** (`core/layers.py`): every garment has a Layer (socks 1, bottoms 2, tops 3, skirt 4). A shell reads the lower garments of the same body through its own `Drape_Under_<garment>` collection (outside the scene, fake user) — shell v16 casts a ray from the skin along its normal and pushes the cloth out past any lower layer (`LAYER_GAP` 6 mm, `LAYER_REACH` 12 cm, enough for Loose garments). A skirt takes lower garments' points into its outline when built. Verified: Loose shorts swallowed a Fitted shirt's hem without layering; with it the hem sits over them
- [x] **Trim** (`core/trim.py`, "Drape Trim" GN modifier, last in the stack): hems (outside faces next to the thickness rim), side/shoulder seams (`drape_side` 0 line) and armholes (`drape_arm` 0.5 line), smoothed as curves and swept into tubes; buttons spaced down the front middle (`drape_center` 0 line, front, not arms), seated 2.5 mm proud, off-white "Drape Buttons" material. Body fields written by Set Up Body
- [x] **Silhouette** preset: Realistic (2.5 mm cloth, fine hems, seams, Fabric) / Anime (5 mm cloth, bold 3 mm hems, no seams, Toon)
- [x] **Drawn details** (`core/details.py`, "Drape Detail" GN modifier on a curve): Strap, Belt, Piping, Zip (tape + metal teeth). Draw Detail → Draw tool on the cloth (surface depth) → Finish Drawing parents it to the nearest *main* bone (physics/twist/helper bones skipped). The modifier keeps the curve on the garment's current surface: moves only along the cloth normal (sliding to the nearest point dragged points to hems), flips normals that face inward (the nearest cloth can be the garment's inside), smooths position and normal along the curve
- [x] **Done when** verified live: anime long-sleeve with 6 buttons over shorts on the VRoid; realistic T-shirt with seams and 5 buttons, a belt round Nova's shorts; a strap drawn through the real operators attached to the upper chest. Panel checked by code for shell, skirt and shorts garments
- [ ] Pockets (patch pockets as stitched panels) — not built
- [ ] Draw Detail is only tested with points added by script between the two operators, not with real mouse strokes in the Draw tool
- [ ] Skirt seams: none (a skirt has no body fields); its hem trim works
- **Hard-won:** (1) a GN modifier's output keeps the *source* mesh's vertex groups — a body shell carries the body's groups and **can't create new ones**, so Solidify's shell/rim marks and cloth pins must use groups that exist on the body (with a 0 weight on every vertex, or they vanish); (2) Solidify marks the *original* (inner) surface as "shell", not the outer copy; (3) skirt faces were wound inward (normals into the body) → flipped; (4) Remove Attribute's pattern mode is "Wildcard", not 'WILDCARD'; (5) Set Curve Normal's mode is an input socket ('Free'); (6) layering collections must stay out of the scene, so details must link to the garment's *scene* collection, not `users_collection[0]`; (7) garments made before a settings fix keep the old Solidify settings — `upgrade_if_needed` now corrects them on load

## Phase 5 — Materials & Style
- [ ] Fabric preset library: cotton, denim, silk, knit, leather — PBR + toon variants
- [ ] Pattern/tiling controls; trim color slots
- [ ] Garment preset save/load (user library, mirror-aware)

## Phase 6 — Rig, Refit & Ship
- [ ] Weight transfer from body → garment follows animation out of the box
- [ ] Refit to morphs: adapt a saved garment to a different body shape (CC morphs / VRoid params)
- [ ] Export: FBX (game/CC pipeline), VRM-compatible output
- [ ] Docs + demo video; package per licensing decision

---

*Verify each phase live via the Blender MCP. If a phase ever feels complicated to use, it's wrong — simplify before moving on.*
