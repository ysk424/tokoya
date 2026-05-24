# Project Working Notes (for future Claude Code sessions)

This file is a handoff log. Read it before doing anything in this repository.
Treat it as a living context document, updated when phases close.

---

## What this project is

A Blender 5.1 extension that will eventually host a **NVIDIA PhysX**-backed
hair simulation. Today the extension is a minimal skeleton; PhysX, GPU,
and C++ solver code are all deliberately deferred to later phases.

Target platform initially: **Windows x64 only**. Avoid choices that
permanently lock out Linux/macOS, but do not test or implement them.

Owner / single developer: `azoo` (GitHub `ysk424`). Communication is
mostly in Japanese — when in doubt, mirror the user's language.

---

## Repository layout (current)

Flat Blender-extension layout at the repo root; native build sources
isolated under `native/`.

```
.
├── CLAUDE.md                    this file
├── blender_manifest.toml        extension manifest (id=hair_sim_physx)
├── __init__.py                  add-on entry (register / unregister, operators,
│                                SolverInterface stub, frame_change_post handler,
│                                Phase 2C probe operator)
├── ui.py                        3D-View N-panel "HairSim" category
├── _native_loader.py            Phase 2D loader: env-var first, bundled fallback
├── native/                      out-of-extension build sources (NOT in zip)
│   ├── probe.cpp                placeholder pybind11 module (PYBIND11_MODULE
│   │                            phase2b_probe { add, phase=2B })
│   ├── setup.py                 setuptools + pybind11 build
│   └── build.cmd                VS 2022 BuildTools wrapper, invokes setup.py
│                                via .venv python; produces
│                                native/phase2b_probe.cp313-win_amd64.pyd
├── .venv/                       (gitignored) system Python 3.13 venv
├── dist/                        (gitignored) built extension zips
├── build/, *.pyd, *.obj, ...    (gitignored) native build artifacts
└── .git, .gitignore, .gitattributes
```

The `[build].paths` whitelist in `blender_manifest.toml` controls
exactly what enters the zip: manifest + `__init__.py` + `ui.py` +
`_native_loader.py` + `native/phase2b_probe.cp313-win_amd64.pyd`. The
.pyd must be present at build time or the extension build fails.

---

## Phase history (load-bearing)

The user enforces strict phase discipline: each phase has a written
design, an explicit GO from the user, and a minimal scope. **Do not
expand scope or merge phases without explicit approval.**

| Phase | Outcome | Commit |
|---|---|---|
| **1** | Minimal extension: Start/Stop/Reset operators, `SolverInterface` stub, `frame_change_post @persistent` handler, WindowManager `hair_sim_running` (SKIP_SAVE), N-panel "HairSim" | `ec6e468` (then layout flatten `5772e97`, manifest paths `2343791`) |
| **2A** | One-shot pybind11 .pyd built with system Python 3.13 imports successfully into Blender 5.1's bundled Python 3.13.9 via sys.path injection. Confirmed ABI compatibility despite patch-level mismatch | (no commit — temp dir experiment) |
| **2B** | Repo-tracked build: `native/probe.cpp`, `native/setup.py`, `native/build.cmd`. Built .pyd is gitignored; built artifact loads from repo via MCP sys.path test | `98a12d6` |
| **2C** | Extension reaches native via `_native_loader.py`. `HAIR_SIM_NATIVE_DIR` env var only. `hair_sim.probe_native` operator (INTERNAL, no UI). Phase 1 invariants preserved | `3dfb125` |
| **2D** | Native .pyd bundled inside extension zip at `<pkg>/native/`. Loader priority γ: **env var first, bundled fallback, None**. Loader uses `importlib.util.spec_from_file_location` and overrides `__file__` to defeat CPython's single-phase extension cache (so the chosen path is visible to callers). `platforms = ["windows-x64"]` added | `4c7e0ec` |
| **3A** | Read-only investigation of `YOKO__EXT_TEST.blend` (`C:\Users\azoo\Documents\Blender\QueSera2\YOKO__EXT_TEST.blend`). Hair = single Curves object `カーブ.001`, 4474 strands × 8 points = 35,792 points, uniform 8 points/curve. Modifier stack: Geometry Nodes "サーフェス変形" (Surface Deform). Evaluated data differs from original (Surface Deform applied). Memory budget table for 1411 frames | (MCP only) |
| **3B** | Read evaluated `position` via `foreach_get` into `array.array('f')` (107,376 floats / 419 KiB per frame) and into `bytearray + memoryview.cast('f')`. Per-frame and 32-frame multi-frame chunks behave identically. Dominant cost = `frame_set` + depsgraph eval ≈ 60 ms/frame; foreach itself is sub-ms | (MCP only) |
| **3C** | Writeback to **original** Curves data works. Direct assignment and `foreach_set` both succeed. `obj.data.update_tag()` + re-`evaluated_depsgraph_get()` propagates to evaluated data. Surface Deform consumes original positions (applies a roughly linear ~0.91× transform on the offset before reaching evaluated coords). Viewport visibly changes once enough strands are moved (~1000+) | (MCP only) |
| **3D** | Full-frame writeback (all 35,792 points). Per-frame deformation total ≈ **46 ms**: depsgraph re-eval **37 ms (~81%)**, Python loop 6.4 ms, foreach_get+set 0.14 ms combined | (MCP only) |
| **3E** | Temporary `frame_change_post` handler drives non-cumulative deformation across frames 800–840. Deterministic (revisit same frame → same shape), Phase 1 handler count unaffected, handler removed cleanly after test. ~110 ms/frame end-to-end via `frame_set` | (MCP only) |

**Phase 3 left no repo changes by design** (MCP-only investigations).
HEAD remains at `4c7e0ec` (Phase 2D).

---

## Critical landmines (Curves / depsgraph work)

These are non-negotiable. They are also saved as a separate memory
entry (`feedback_curves_landmines.md`); read both.

1. **Write to original, observe via evaluated.** Never write to
   evaluated data; treat evaluated objects as read-only snapshots.
2. **Original-space offset ≠ evaluated-space offset.** Surface Deform /
   Geometry Nodes transform the result. Only require "some evaluated
   change occurs," not a specific value.
3. **Don't persist evaluated / depsgraph references.** Acquire, read,
   discard. They are session-temporary.
4. **Attribute domains have different lengths.** POINT-domain `position`
   has 35,792 entries on `カーブ.001`; CURVE-domain
   `surface_uv_coordinate` has 4474. Never flatten under one length.
5. **`bpy.data.is_dirty` is unreliable for Curves writes.** Phases 3C/3D/3E
   all modified Curves memory while `is_dirty` stayed `False`. Falsy
   `is_dirty` is not evidence the scene is unchanged. **Never use it
   to gate save decisions.**
6. **After any destructive Curves test, never `Ctrl+S`.** Recover via
   `File > Revert`, reload, or close without saving.
7. **Don't wire writeback into `frame_change_post` permanently yet.**
   Phase 3E proved the path works as a one-off; production wiring is a
   separate risk class (timing, viewport, threading) and needs its own
   phase.
8. **In the Curves-validation branch, never introduce PhysX / CUDA /
   GPU / C++ transfer / numpy / SolverInterface wiring.** Those are
   deferred and must remain deferred until explicitly unblocked.
9. **Don't over-optimize foreach_get/set.** They are µs-class.
   Dominant cost is `frame_set` + depsgraph + Surface Deform
   (~60–110 ms/frame). Optimize the right end.
10. **No single giant contiguous allocation.** Work in chunked
    contiguous buffers (per-frame / N-frame chunk / strand-group).
    Working tentative direction: "chunked contiguous + float32."

---

## Placeholders not yet finalized

These names are intentional placeholders. Each is confined to **one
location** so a future phase can rename in a single edit. Do not spread
them.

| Placeholder | Location | Finalize in |
|---|---|---|
| Native module name `phase2b_probe` | `native/probe.cpp` (PYBIND11_MODULE), `_native_loader.py` (`_MODULE_NAME`), `blender_manifest.toml` (`[build].paths`) | When solver shape is known |
| `_native_loader.py` / `get_native()` | `_native_loader.py`, `__init__.py` operator import | When the boundary API stabilizes |
| `HAIR_SIM_NATIVE_DIR` env var | `_native_loader.py` (`_ENV_VAR`) | When dev/prod split is real |
| Bundled subdir `native` | `_native_loader.py` (`_BUNDLED_SUBDIR`) | Same |

---

## Current operational state

* Latest user-installed extension version is whatever was last built into
  `dist/`. Manifest in repo is `0.0.4`. **Always bump `version` in
  `blender_manifest.toml` before producing a new zip the user will
  install** (`feedback_version_bump.md`); otherwise Blender's
  install-from-disk refuses without manual uninstall.
* Uninstall via CLI when needed (full path required):
  `"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --command extension remove hair_sim_physx`
  Blender must be **fully closed** first (DLL is locked while loaded).
* Manual UI install: `Edit > Preferences > Get Extensions > Install from Disk`
  with the zip in `dist/`. Then **restart Blender** for native module
  isolation.
* Verification pattern: MCP-driven in a freshly restarted Blender.
  Always check Phase 1 invariants at the end (handler count = 1,
  `hair_sim_running == False`, object count unchanged, `git status`
  clean).

### Phase 1 invariants (must remain true)

* `bpy.app.handlers.frame_change_post` contains exactly **one** handler
  with `__module__` starting with `bl_ext.user_default.hair_sim_physx`.
* `bpy.context.window_manager.hair_sim_running` exists, defaults
  `False`, is `SKIP_SAVE`.
* Operators `hair_sim.start`, `hair_sim.stop`, `hair_sim.reset` are
  idempotent no-ops on re-entry, do not depend on native availability,
  and never appear in the operator search (`HAIR_SIM_OT_probe_native`
  is `INTERNAL`).
* `ui.py` and `blender_manifest.toml` semantics unchanged across
  Phase 2 sub-phases; only Phase 2D added `version`, `platforms`, and
  one `[build].paths` entry.

---

## Development workflow

* Python: system Python 3.13.13 (`py -3.13`) → `.venv/` (already
  created). pybind11 3.0.4, setuptools, ninja, scikit-build-core are
  installed (the latter two are unused in the current setup but
  available).
* MSVC: Visual Studio 2022 BuildTools, MSVC 14.44.35207 at
  `C:\Program Files\Microsoft Visual Studio\2022\BuildTools\`.
* Build native .pyd: `native/build.cmd` (initializes vcvars64, calls
  setup.py via `.venv` python).
* Build extension zip:
  `"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --command extension build --source-dir . --output-dir dist`
* The user runs Blender. Many tests need the user to manually restart
  Blender between iterations because Windows holds .pyd DLL handles
  for the lifetime of the process. Plan tests around restart points.
* MCP is the primary test harness. Prefer one-shot MCP scripts over
  adding throwaway operators to the extension.

---

## Branches

* `main` — current line of work, HEAD `4c7e0ec` (Phase 2D).
* `phase2-cpp` — quarantined early scaffolding (full C++/PhysX/CMake/
  scikit-build-core/scripts/extern submodule) that was stripped from
  main when Phase 1 was reset. Reference only — do not cherry-pick
  blindly. Re-derive cleanly per phase instead.

---

## Memory (`.claude/projects/.../memory/`)

The harness loads these on startup. Cross-reference them, don't
duplicate. Update them rather than the inline list when feedback
arrives.

* `feedback_version_bump.md` — bump manifest version every install
  iteration.
* `feedback_curves_landmines.md` — the 10 Curves rules above (longer
  version with reasons).

---

## Pending / next phase candidates (not yet designed)

These are *candidates* surfaced by Phase 3 results. None are committed
to. Each needs its own design pass + user GO before implementation:

* **Phase 3F (?)** — turn the Phase 3E proof-of-concept into a
  reviewable operator or design note. Still pure Python, still no
  native, still no SolverInterface wiring.
* **Phase 3G (?)** — bench the cost of chunked buffers across a longer
  frame range (still Python).
* **Phase 4 (?)** — first SolverInterface wiring (still no PhysX): use
  the existing pybind11 boundary to compute trivial per-frame
  transformation in native code, measure round-trip latency.
* **Phase 5+ (?)** — PhysX SDK, CUDA, GPU integration. Far away.
  Quarantined `phase2-cpp` branch has reference material.

When a new phase begins, do not skip steps:
1. Wait for a design request from the user.
2. Produce a design doc (options / risks / minimum completion
   criteria / Desktop alignment points) in the chat — no
   implementation.
3. Iterate on the design until the user issues an explicit GO with
   modifications.
4. Implement minimally; verify via MCP; report results.
5. Commit only what was approved; never add docs / operators / files
   the user did not ask for.

---

## Things the user has been explicit about

* Tests pass/fail criteria belong to the user, not the implementer.
* "**実装は禁止です**" / "実施禁止です" means hard stop — produce a
  design only.
* When asked to push or commit, check `git status` first. If nothing
  is staged or modified, say so rather than synthesizing artifacts.
* Do not create README/docs files unless asked.
* Do not run UI/visual checks by yourself — the user is at the
  keyboard and prefers verifying visually after explicit work.
* When Blender state matters, the user prefers to restart Blender
  themselves; coordinate by asking "終了完了 / 起動完了" markers.
* Default to Japanese in chat unless the user switches.
