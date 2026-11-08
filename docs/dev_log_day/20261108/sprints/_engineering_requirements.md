# Engineering requirements — BINDING for every sub-sprint in this directory

`datavibes` is a **standalone** repo (no VBWD core / plugin oracle applies),
but it inherits the same engineering discipline as the parent SDK. Re-stated here so
every sprint file in this day can link a single anchor.

## The core requirements (no exceptions)

1. **TDD-first** — red → green → refactor; no production code without a failing test.
   Processing steps are pure functions → unit-test them directly with fixtures.
2. **DevOps-first** — works from a cold clone, local **and** CI. `pip install -e .`
   then the CLI runs; a `run` on a fixture dataset produces a byte-stable snapshot.
   Sources that hit the network are mocked/recorded in tests — **CI never depends on a
   live third-party API**.
3. **SOLID**
   - **SRP** — Source *fetches*, Generator *snapshots*, Processor *transforms*,
     Exporter *writes*. One responsibility each.
   - **OCP** — new data sources and new processing steps register into a registry;
     you never edit the SDK to add a dataset.
   - **LSP** — every `Source` subtype honours `fetch(ctx) -> Iterable[record]`; a
     failing/empty source degrades to an empty snapshot, never a crash mid-pipeline.
   - **ISP** — narrow interfaces (`Source`, `ProcessingStep`, `Writer`).
   - **DIP** — the pipeline depends on the `Source` / `ProcessingStep` / `Writer`
     abstractions and on config, never on a concrete provider.
4. **DI** — collaborators (sources, steps, writers, clock, filestore) are passed in /
   resolved from the registry; no hidden singletons, no module-level network clients.
5. **DRY** — one home per behaviour; the SDK holds all reusable machinery **once**,
   datasets hold only declarative config.
6. **Clean code** — full readable names ([[feedback_variable_naming]]); no
   overengineering — do not build a source adapter until a dataset needs it.
7. **Determinism** — same config + same injected timestamp ⇒ identical output bytes.
   The wall clock is injected, never read inside pure code (mirrors the workflow-script
   rule against `Date.now()` in deterministic contexts).
8. **CLI-only + importable** — the *only* human interface is the `datavibes`
   console script; everything it does is also reachable via `import datavibes`.
   No second UI, no server.
9. **Public sources only** — data comes from documented public APIs / files. No manual
   data entry, no per-customer bespoke scraping (the automation rules from the product
   brief are binding here too).

## Output contract (binding)

Snapshots land at `output/<category>/<slug>-<hash>/<YYYY-MM-DD-HH-MM>.csv` — the exact
shape the VBWD `dataset` plugin ([[project_s110_datasets_plugin]]) serves. This repo
writes files; it never imports or calls the plugin.
