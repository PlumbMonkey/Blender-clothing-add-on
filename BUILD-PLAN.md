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

## Phase 1 — Body Setup
- [ ] Import normalization: CC / VRoid / generic body detection (reuse from core)
- [ ] Body region masks: torso, arms, legs, hips, feet (auto-guess + paint refine)
- [ ] Surface-snapped curve drawing on the body (reuse from core)
- [ ] **Done when:** a CC body and a VRoid body are each garment-ready in under a minute

## Phase 2 — Garment Generation MVP  → *first shippable*
The core trick: paint coverage → get a garment. Non-destructive throughout.

- [ ] Paint garment coverage on body (mask) → GN generates an offset shell: solidify, smooth borders, adjustable offset/thickness
- [ ] Boundary curves auto-extracted from mask edges → editable necklines, sleeve ends, hems
- [ ] Garment presets from coverage templates: t-shirt, tank, shorts, pants, skirt, socks
- [ ] Toon + simple PBR fabric materials (one click)
- [ ] **Done when:** a t-shirt and shorts on a VRoid model in ~10 minutes, and editing the mask updates the garment live

## Phase 3 — Fit & Simulation
- [ ] Collision/shrinkwrap fit pass with adjustable tightness (skin-tight ↔ loose)
- [ ] Cloth sim presets: drape / settle / windy — pin groups auto-set at waist, shoulders, cuffs
- [ ] Bake sim result to shape key (keep the procedural base intact)
- [ ] **Done when:** a loose skirt drapes believably with one click

## Phase 4 — Details & Tailoring
Where garments stop looking like shells. (Reuses Wisp's instance-along-curve tech.)

- [ ] Seams and hems: instanced trim geometry along boundary curves
- [ ] Detail curves drawn on garment → pockets, straps, belts, zippers, buttons (instanced assets)
- [ ] Layering: garment-over-garment offset handling (shirt under jacket without clipping)
- [ ] Edge loops/thickness controls for stylized (anime) vs realistic silhouettes

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
