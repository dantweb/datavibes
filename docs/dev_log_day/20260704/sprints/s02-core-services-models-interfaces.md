# S02 — Core: services, models & interfaces

**Date:** 2026-07-04 · **Type:** Sprint plan · **Status:** 🟡 PLANNED
**Requirements:** binding — [`_engineering_requirements.md`](_engineering_requirements.md)
(TDD-first · DevOps-first · SOLID via registries · DI · DRY · deterministic ·
CLI-only + importable · public-sources-only).
**Architecture basis:** [`s01-dataset-generator.md`](s01-dataset-generator.md).

**Trigger.** The generator / processor / exporter sprints (S03–S05) all stand on the
same backbone: typed schema, dataset config, the three plug-in interfaces, their
registries, the on-disk store, an injected clock, and the `DatasetSDK` facade + CLI
shell. Build that backbone **once**, fully tested, so the later sprints only add
concrete strategies.

**Area.** `datavibes/` package foundation. No network, no data transforms yet — just the
contracts and the wiring.

---

## The one rule this sprint enforces

> **Everything downstream depends on abstractions defined here, never on each other's
> concretes.** Generator, Processor, Exporter each depend only on the ABCs + registries
> + store + config models in this sprint. Nothing in `datavibes/` reads the wall clock,
> the network, or a concrete provider directly.

---

## Deliverables

### 1. Schema — `datavibes/schema/field.py`
- `Field(name, dtype, nullable=False, unit=None, description=None, transform=None)`.
  `dtype ∈ {str,int,float,bool,date}`.
- `Schema(fields: list[Field])` with:
  - `column_names()` — ordered names (the single source of output column order).
  - `coerce(row: dict) -> dict` — cast each value to its `dtype` (raise on bad).
  - `validate(rows) -> None` — assert every row matches names + dtypes + nullability.
- **Tests:** coercion per dtype, `date` parsing, nullable vs. non-null violation,
  unknown-column rejection, column ordering stability.

### 2. Config models — `datavibes/config/models.py`
- `DatasetMetadata(slug, title, category, license, update_frequency, attribution)`.
- `SourceSpec(type: str, options: dict)`, `StepSpec(name: str, options: dict)`.
- `DatasetConfig(metadata, schema: Schema, sources: list[SourceSpec], processing:
  list[StepSpec])`.
- Validation: slug is kebab-case, category non-empty, ≥1 source, schema non-empty.
- **Tests:** valid config round-trips; each invariant violation raises a precise error.

### 3. Config loader — `datavibes/config/loader.py`
- `load_config(path) -> DatasetConfig` from `dataset.yaml`; resolves `schema` entries to
  `Field`s and `sources`/`processing` to specs. **No** source/step instantiation here
  (that needs the registries — lazy, at run time).
- `discover(root) -> list[str]` — list dataset slugs under `datasets/`.
- **Tests:** load a fixture yaml → expected `DatasetConfig`; malformed yaml → clear error;
  `discover` finds fixtures, ignores non-dataset dirs.

### 4. Interfaces — `datavibes/interfaces.py`
Single-method ABCs (ISP):
```python
class Source(ABC):
    @abstractmethod
    def fetch(self, ctx: "FetchContext") -> Iterable[dict]: ...

class ProcessingStep(ABC):
    @abstractmethod
    def apply(self, rows: list[dict], ctx: "RunContext") -> list[dict]: ...

class Writer(ABC):
    @abstractmethod
    def write(self, rows: list[dict], schema: Schema, dest: Path) -> Path: ...
```
- **Tests:** trivial in-test subclasses satisfy each contract (Liskov smoke).

### 5. Registries — `datavibes/registry.py`
- `SOURCE_REGISTRY`, `STEP_REGISTRY`, `WRITER_REGISTRY` (name → class).
- Decorators `register_source(name)`, `register_step(name)`, `register_writer(name)`.
- `resolve_source(spec) / resolve_step(spec) / resolve_writer(name)` — construct with
  `options`; unknown name → `UnknownStrategyError` naming the missing key.
- **Tests:** register + resolve; duplicate-name guard; unknown-name error message.

### 6. Run context & clock — `datavibes/context.py`
- `Clock` protocol + `FixedClock(ts)` (tests/CI) and `SystemClock` (prod). The clock is
  **always injected** (determinism req. §7 — no `datetime.now()` in pure code).
- `FetchContext(config, clock, http)` and `RunContext(config, clock)`.
- **Tests:** `FixedClock` returns the injected instant; timestamp formatting
  `YYYY-MM-DD-HH-MM` is stable.

### 7. Store — `datavibes/store/filestore.py`
- Owns the on-disk layout and the stable `<slug>-<hash>` folder identity (hash derived
  deterministically from slug — same slug ⇒ same folder).
- `raw_path(slug, ts)` → `store/raw/<slug>/<ts>.jsonl`.
- `output_path(category, slug, ts)` →
  `output/<category>/<slug>-<hash>/<YYYY-MM-DD-HH-MM>.csv` (the delivery contract).
- `write_raw(...)`, `read_latest_raw(slug)`, `latest_output(slug)`.
- **Tests:** path builders match the contract byte-for-byte against a real
  `air-quality-<hash>/<ts>.csv` sample; `<hash>` is stable across runs; latest-snapshot
  selection.

### 8. SDK facade + CLI shell (skeletons) — `datavibes/sdk.py`, `datavibes/cli.py`
- `DatasetSDK(root, clock=SystemClock(), store=FileStore(...))` — DI seams.
- Methods present as thin skeletons that raise `NotImplementedError` where S03–S05 fill
  in (`generate`, `process`, `export`), but `list()` / `validate(slug)` / `info(slug)`
  work now on top of loader + store.
- `cli.py` argparse shell mapping `list/new/validate/generate/process/run/export/info`
  onto the facade; `new <slug>` scaffolds a `static`-source `dataset.yaml`.
- **Tests:** CLI smoke (`--help`, `list`, `validate` on fixture); `new` writes a config
  that immediately passes `validate`.

---

## Scope

**IN:** items 1–8 above with tests; `pyproject.toml` + `datavibes` console script; cold
`pip install -e .` green.
**OUT:** any concrete `Source`/`ProcessingStep`/`Writer` beyond the `static` source and a
no-op writer needed for the facade skeleton (those are S03–S05).

## SOLID mapping
- **SRP** — schema, config, registry, store, context each isolated.
- **OCP** — registries are the only extension seam the later sprints touch.
- **LSP** — ABC contracts + Liskov smoke tests.
- **ISP** — three single-method interfaces.
- **DIP** — facade takes `clock`/`store` by injection; nothing imports a concrete strategy.

## Definition of done
- [ ] `pip install -e .`; `datavibes --help`, `datavibes list`, `datavibes validate <fixture>` work.
- [ ] Every module above has unit tests; suite green from a cold clone with no network.
- [ ] `FileStore.output_path` matches a real `air-quality-*` snapshot path exactly.
- [ ] `new` → `validate` round-trips green.
