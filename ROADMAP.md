# Scout — Handoff & Remaining Work

## What Scout Does

Scout is a local project knowledge base builder. It runs in three stages:

1. **Structural Dump** — runs [repomix](https://github.com/yamadashy/repomix) to produce a structured XML snapshot of a project's source tree
2. **Knowledge Compilation** — feeds the XML through a local Ollama model to generate `architecture.md` (human-readable overview) and `dependencies.json` (machine-readable module graph)
3. **Vector Index** — uses the sibling [kb](../kb/) tool to split source files into semantic chunks, embed them locally, and store them in ChromaDB for natural-language search

Nothing leaves the machine. No API keys.

### Project Layout

```
scout/
  bin/scout          — CLI orchestrator (bash, ties all three stages together)
  compile.py         — Python: XML parsing, chunking, Ollama orchestration, dependency graph
  install.sh         — Installs scout into PATH + Pi skill
  skill/SKILL.md     — Pi skill (copied to ~/.pi/agent/skills/scout/ by install.sh)
  tests/
    test_compile.py  — Unit tests for compile.py pure functions (74 tests)

kb/                  — Sibling project (vector indexing and query)
  main.py            — CLI entry point (typer)
  indexer.py         — ChromaDB indexing, incremental upsert
  chunker.py         — Structure-aware file chunking (fn/class boundaries)
  query.py           — Embed query, cosine similarity search
  utils.py           — File walking, MIME-type filtering
  db.py              — Shared embedding model + ChromaDB client
  requirements.txt   — Python deps (chromadb, sentence-transformers, typer)
```

### Repomix

Repomix lives separately at `../repomix/` and is invoked via `node ../repomix/run.js`. Scout depends on it being present at that path (checked in `bin/scout` preflight).

---

## Status

| #  | Item | Status |
|----|------|--------|
| 1  | Stable chunk IDs (content-hash based) | ✅ Shipped |
| 2  | Ground-truth dependency graph (`--emit-deps`) | ✅ Shipped + gaps fixed |
| —  | Immediate cleanup todos (non-blocking) | ✅ Shipped |
| 3  | Extended chunk metadata (conservative) | ✅ Shipped |
| 4  | Index architecture.md into vector store | ✅ Shipped |
| 5  | `kb index --name` and `--tag` flags | ✅ Shipped |
| 6  | Pi skill | ✅ Shipped |

---

## Shipped — Items 1 & 2

### Item 1 — Stable chunk IDs

Chunk IDs are now content-hash based (`SHA-256`, 16-char hex) rather than position-based (`{path}::chunk{i}`). A function moving down a file no longer changes its ID. Implemented in `kb/chunker.py`:

```python
def chunk_id(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]
```

The file-context header (`// File: {path}\n`) is included in the hash, so a chunk from a renamed file correctly gets a new ID.

Incremental re-indexing in `kb/indexer.py` uses these IDs as existence checks — no secondary hash needed.

### Item 2 — Ground-truth dependency graph (`--emit-deps`)

`compile.py` now supports `--emit-deps`, which builds `dependencies.json` directly from import resolution rather than asking the LLM to infer it from `architecture.md`.

**Implementation:** `build_dependency_graph(files, project_name)` runs `_extract_refs` / `_resolve_ref` over every parsed file and produces a deterministic edge list. No LLM involved.

**Schema** (forward-compatible with future semantic edges):

```json
{
  "nodes": [
    { "id": "src/main.rs", "type": "rust", "parseable": true }
  ],
  "edges": [
    { "from": "src/main.rs", "to": "src/commands.rs", "kind": "imports" }
  ],
  "meta": {
    "project": "myapp",
    "ipc_commands": [],
    "unresolved_refs": [
      { "from": "src/foo.ts", "ref": "./icon.type" }
    ]
  }
}
```

**Fixes included:**

- **`parseable` field** — every node has `"parseable": true|false` based on whether `_ext_key` matched a known language. Config files, markdown, etc. get `false`.
- **`unresolved_refs`** — local refs (starting with `.` or `/`) that failed to resolve are collected in `meta.unresolved_refs`. Third-party package imports are silently filtered.
- **Extension-append resolution** — `_resolve_ref` now tries appending extensions (`.ts`, `.tsx`, etc.) to the raw path, catching refs like `./icon.type` → `icon.type.ts`.
- **Nodes from file list** — all parsed files appear as nodes regardless of whether they have any edges.
- **Edge deduplication** — via `set` of `(from, to)` tuples before serialisation.

**Sanity check results** (Rust/Tauri/React app):

- 156 config/asset files correctly show `parseable: false`
- 167 edges found including real cross-file imports
- 6 unresolved refs, all genuine local modules not included in the repomix dump
- Zero third-party import leakage

---

## Shipped — Cleanup

Three non-blocking cleanup items resolved:

1. **Removed unused `_chunk_hash`** from `indexer.py` — `chunk_id` from `chunker.py` does the same job
2. **Removed unused `chunk_id` import** from `indexer.py` — the ID is already on the chunk dict
3. **Tightened exception handling** in `query.py` — `get_collection` now catches `chromadb.errors.NotFoundError` specifically instead of bare `Exception`

---

## Shipped — Item 3: Extended chunk metadata

Enriched ChromaDB chunk metadata with structural context, no LLM involved.

**`kb/indexer.py`:**
- `EXT_LANG_MAP` — file extension → language inference (17 extensions mapped)
- Optional `dependencies.json` loading from `~/.scout/projects/<name>/`
- `_chunk_metadata` now emits `language` (always), `dependencies` (comma-separated string, only when edges exist), and `tag` (when provided)
- Graceful degradation: falls back to extension map when no dep graph exists

**Tests:** 16 tests in `test_indexer.py` covering language from extension/dep graph, dependencies present/absent, tags present/absent, core fields.

---

## Shipped — Item 4: Index architecture.md into vector store

`~/.scout/projects/<name>/architecture.md` is now automatically included in the kb vector index when it exists.

**`kb/indexer.py`:** After `load_files()`, checks for `architecture.md` and appends it with virtual path `.scout/architecture.md` — avoids leaking home directory paths. Content-hash IDs handle dedup on re-index.

**`kb/chunker.py`:** New `_split_md()` function splits Markdown on `#{1,3}` heading boundaries (h1–h3), falling back to sliding window for single-section files. Added `elif ext == "md"` branch in `chunk_file()`.

**Tests:** 6 new tests in `test_chunker.py` — heading split, single-heading fallback, virtual path preservation, multi-section split, indexer with/without architecture.md.

---

## Shipped — Item 5: `kb index --name` and `--tag` flags

**`kb/main.py`:**
- `index` — `--name` / `-n` overrides ChromaDB collection name, `--tag` / `-t` attaches tag to all chunks
- `query` — `--tag` / `-t` filters results via ChromaDB `where` clause

**`kb/indexer.py`:** — `index_project(path, name=None, tag=None)` forwards both params
**`kb/query.py`:** — `query_project(..., tag=None)` passes `where={"tag": tag}` when set

**Tests:** 2 tag tests in `test_indexer.py`, 2 filter tests in `test_query.py`.

**Usage:**
```bash
kb index ~/my-app --name my-app --tag v1
kb query my-app "how does auth work" --tag v1
```

---

## Shipped — Item 6: Pi Skill

**`scout/skill/SKILL.md`** — Version-controlled Pi skill that teaches Pi when and how to run scout and query the resulting knowledge base. Covers: when to use, prerequisites, step-by-step flow (check existing index → run scout → load architecture context → query), project name inference, and error handling.

**`scout/install.sh`** — Now copies the skill to `~/.pi/agent/skills/scout/SKILL.md` during installation.

Pi discovers skills automatically — no registration needed. The skill references the `kb-search` skill for query detail.

---

## Tests Summary

**28 tests, all passing:**

| File | Count | Coverage |
|------|-------|----------|
| `test_indexer.py` | 16 | Language from extension, language from dep graph, dependencies present/absent, tags present/absent, core fields |
| `test_chunker.py` | 10 | MD heading split, single-heading fallback, chunk ID stability, rename detection, virtual path preservation, architecture.md loading (with/without) |
| `test_query.py` | 3 | NotFoundError handling, tag filter wiring, no-filter default |

---

## Phase 2 — Query Enrichment Layer

Depends on Items 2, 3, and 4 being proven reliable. Not started.

Planned flow:

```
user question
    → embed → top-k chunks from ChromaDB
    → look up those file paths in dependencies.json → fetch import neighbours
    → prepend relevant section of architecture.md
    → send assembled context to model
```

Requires a new `kb query --enriched` mode and graph traversal logic in `query.py`.

---

## Phase 3 — Obsidian Integration (future)

`architecture.md` is already valid as an Obsidian note — drop it into your vault manually.

Optional future addition: a `--obsidian` flag on scout that post-processes `architecture.md`
and replaces module name references with `[[wikilinks]]` derived from the dependency graph.
No implementation work needed until then.

---

## Running Tests

```bash
cd /Users/carl/tools/kb
python3.11 -m pytest tests/ -v
```

Note: Python 3.11 required for pytest (system 3.14 has broken `pyexpat`/pip). `compile.py` itself works on 3.14 since it avoids `pyexpat`.

---

## Dependencies

### Scout

- Node.js (for repomix)
- Python 3.10+
- Ollama at `http://localhost:11434`
- repomix at `../repomix/run.js`

### kb

- Python 3.10+
- `chromadb`
- `sentence-transformers` (model: `all-MiniLM-L6-v2`)
- `typer`

### Repomix

- Node.js 18+
