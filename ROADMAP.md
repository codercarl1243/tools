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
  install.sh         — Installs scout into PATH
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
| —  | Immediate cleanup todos (non-blocking) | ⚠️ Pending |
| 3  | Extended chunk metadata (conservative) | **Ready** — not started |
| 4  | Index architecture.md into vector store | **Ready** — not started |
| 5  | `kb index --name` and `--tag` flags | **Ready** — not started |
| 6  | Pi skill | **Ready** — not started |

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

## Immediate Cleanup Todos

Non-blocking but worth doing before or alongside Item 3.

### `kb/indexer.py` — remove unused `_chunk_hash`

`_chunk_hash` is defined in `indexer.py` but never called. `chunk_id` from `chunker.py` does the same job and is what's actually used for IDs. Safe to delete.

```python
# DELETE this function — it's unused
def _chunk_hash(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()
```

### `kb/indexer.py` — clean up unused `chunk_id` import

`indexer.py` imports `chunk_id` from `chunker` but never calls it directly — the ID is already on the chunk dict when it arrives. Remove from the import line:

```python
# Before
from chunker import chunk_file, chunk_id

# After
from chunker import chunk_file
```

### `kb/query.py` — tighten bare `Exception` on `get_collection`

```python
# Before — catches everything including bugs
try:
    collection = client.get_collection(project_name)
except Exception:
    print(f"No index found for '{project_name}'. Run: kb index <path>")
    return []

# After — only catches the expected not-found case
import chromadb
try:
    collection = client.get_collection(project_name)
except chromadb.errors.NotFoundError:
    print(f"No index found for '{project_name}'. Run: kb index <path>")
    return []
```

Note: verify the exact exception class name against your installed chromadb version — it may be `InvalidCollectionException` or similar depending on version.

---

## Item 3 — Extended chunk metadata (conservative)

### What it is

Currently each chunk stored in ChromaDB has minimal metadata:

```python
{
    "path": c["path"],
    "chunk": c["chunk_index"],
}
```

The goal is to enrich this with structural context derivable from path and the dependency graph — no LLM judgment calls.

### Target schema

```python
{
    "path": "src/components/Button.tsx",
    "chunk": 0,
    "language": "typescript",          # from file extension or dep graph node type
    "dependencies": "src/utils.ts,src/theme.ts",  # comma-separated (ChromaDB limitation)
}
```

**ChromaDB metadata constraint:** values must be flat strings, numbers, or booleans. No nested structures or arrays. Dependencies stored as comma-separated string.

**Graceful degradation:** if `dependencies.json` doesn't exist (project indexed without scout), only `language` is set. Everything else is omitted rather than set to a placeholder.

### Where to implement

Changes live entirely in `kb/indexer.py` in `_chunk_metadata`. The `module` field was considered but dropped — path-based module inference is too unreliable across different project structures to be worth the noise.

### Concrete implementation steps

1. **Define `EXT_LANG_MAP`** in `kb/indexer.py` (parallel to `compile.py`'s `NODE_TYPE_MAP`):

```python
EXT_LANG_MAP = {
    ".rs": "rust", ".ts": "typescript", ".tsx": "react",
    ".js": "javascript", ".jsx": "react", ".py": "python",
    ".go": "go", ".c": "c", ".cpp": "cpp", ".h": "c",
    ".vue": "vue", ".svelte": "svelte", ".json": "config",
    ".yaml": "config", ".yml": "config", ".toml": "config",
}
```

2. **Load dependency graph** after deriving `project_name`, before chunking:

```python
import json

scout_dir = os.path.expanduser(f"~/.scout/projects/{project_name}")
deps_path = os.path.join(scout_dir, "dependencies.json")
dep_graph = None
node_lookup = {}
file_deps = {}

if os.path.exists(deps_path):
    with open(deps_path) as f:
        dep_graph = json.load(f)
    node_lookup = {n["id"]: n for n in dep_graph.get("nodes", [])}
    for edge in dep_graph.get("edges", []):
        file_deps.setdefault(edge["from"], []).append(edge["to"])
```

3. **Extend `_chunk_metadata`**:

```python
def _chunk_metadata(c: dict, node_lookup: dict = None, file_deps: dict = None) -> dict:
    meta = {
        "path": c["path"],
        "chunk": c["chunk_index"],
    }
    path = c["path"]

    # Language — prefer dep graph node type, fall back to extension
    if node_lookup and path in node_lookup:
        meta["language"] = node_lookup[path].get("type", "other")
    else:
        ext = os.path.splitext(path)[1].lower()
        meta["language"] = EXT_LANG_MAP.get(ext, "other")

    # Dependencies — only if dep graph available and file has outgoing edges
    if file_deps and path in file_deps:
        meta["dependencies"] = ",".join(file_deps[path])

    return meta
```

4. **Update the call site** in `index_project` to pass the lookups:

```python
metadatas=[_chunk_metadata(c, node_lookup=node_lookup, file_deps=file_deps) for c in batch]
```

5. **Add tests** covering:
   - `language` set correctly from extension when no dep graph
   - `language` taken from node type when dep graph present
   - `dependencies` absent when file has no edges
   - `dependencies` is comma-separated string when edges exist
   - No `KeyError` when dep graph exists but file path isn't in it

---

## Item 4 — Index architecture.md into vector store

### What it is

`~/.scout/projects/<name>/architecture.md` is generated by scout but never included in the kb vector index. Queries about architecture never surface it.

### Concrete implementation steps

1. **After file loading in `index_project`**, check for and append `architecture.md`:

```python
arch_path = os.path.expanduser(f"~/.scout/projects/{project_name}/architecture.md")
if os.path.exists(arch_path):
    content = open(arch_path, encoding="utf-8").read()
    if content.strip():
        files.append({
            "path": ".scout/architecture.md",
            "content": content,
        })
```

The virtual path `.scout/architecture.md` keeps chunk metadata clean and avoids leaking home directory paths.

2. **Add heading-aware chunking for `.md`** in `kb/chunker.py`:

```python
_MD_BOUNDARY = re.compile(r'(?:^|\n)(#{1,3}\s+.+)')

def _split_md(content: str) -> list[str]:
    boundaries = [m.start() for m in _MD_BOUNDARY.finditer(content)]
    if len(boundaries) < 2:
        return _sliding_window(content)
    sections = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(content)
        sections.append(content[start:end].strip())
    return _flatten(sections)
```

Then in `chunk_file()`:

```python
elif ext == "md":
    texts = _split_md(content)
```

3. **Add tests** verifying:
   - Project with `architecture.md` produces chunks with path `.scout/architecture.md`
   - Project without `architecture.md` indexes normally with no error
   - Heading boundaries split correctly

### Notes

- Content-hash IDs handle dedup automatically on re-index — no special caching needed.
- `dependencies.json` as a text blob is lower priority; skip for now.

---

## Item 5 — `kb index --name` and `--tag` flags

### What it is

Two CLI additions to `kb index`:

- **`--name`** — override the ChromaDB collection name (default: directory basename)
- **`--tag`** — attach a tag string to every chunk's metadata, filterable at query time

### Concrete implementation steps

1. **`kb/main.py`** — add flags to `index` command:

```python
@app.command()
def index(
    path: str = typer.Argument(..., help="Path to the project root"),
    name: str = typer.Option(None, "--name", "-n", help="Override project name"),
    tag:  str = typer.Option(None, "--tag",  "-t", help="Tag to attach to all chunks"),
):
    index_project(path, name=name, tag=tag)
```

2. **`kb/indexer.py`** — update `index_project` signature:

```python
def index_project(project_path: str, name: str = None, tag: str = None) -> int:
    project_name = name or os.path.basename(project_path.rstrip("/"))
```

3. **`_chunk_metadata`** — add tag if provided:

```python
def _chunk_metadata(c, node_lookup=None, file_deps=None, tag=None):
    meta = { ... }
    if tag is not None:
        meta["tag"] = tag
    return meta
```

4. **`kb/main.py`** — add `--tag` filter to `query` command:

```python
@app.command()
def query(
    project: str = typer.Argument(...),
    q:       str = typer.Argument(...),
    k:       int = typer.Option(5),
    fmt:     str = typer.Option("print"),
    tag:     str = typer.Option(None, "--tag", "-t", help="Filter to chunks with this tag"),
):
    query_project(project, q, k=k, output=fmt, tag=tag)
```

5. **`kb/query.py`** — pass `where` filter to ChromaDB:

```python
def query_project(project_name, query, k=5, output="print", tag=None):
    ...
    where = {"tag": tag} if tag else None
    results = collection.query(
        query_embeddings=[query_vec],
        where=where,
        n_results=k,
    )
```

6. **Add tests** for:
   - `--name` produces collection named correctly, not after directory basename
   - `--tag` appears in chunk metadata
   - Query with `--tag` filters results correctly

### Usage

```bash
kb index ~/design-system --name my-ds --tag type=design-system
kb index ~/my-app        --name my-app

kb query my-ds "button variants" --tag type=design-system
```

---

## Item 6 — Pi Skill

### What it is

A Pi skill at `~/.pi/agent/skills/scout/SKILL.md` that teaches Pi when and how to run scout and query the resulting knowledge base.

### Concrete implementation steps

1. Create `scout/skill/SKILL.md` in the repo (version-controlled copy).

2. Add to `install.sh`:

```bash
mkdir -p "$HOME/.pi/agent/skills/scout"
cp "$SCRIPT_DIR/skill/SKILL.md" "$HOME/.pi/agent/skills/scout/SKILL.md"
```

3. **`SKILL.md` content:**

```markdown
# Scout — Project Knowledge Base

## When to use

- The user asks about project architecture, module structure, or how components connect
- You need to understand an unfamiliar codebase before making changes
- The user asks "how does X work?" where X spans multiple files
- The user explicitly mentions scout or kb

## Prerequisites

- `scout` in PATH
- `kb` in PATH
- Ollama running at http://localhost:11434

## Steps

### 1. Check for existing index

Look for `~/.scout/projects/<project-name>/architecture.md`. If it exists, skip to step 3.

### 2. Run scout

scout <project-path>

Typical completion times:
- <100 files: 2–5 min
- 100–500 files: 5–15 min
- 500+ files: 15–30 min

### 3. Load architecture context

Read `~/.scout/projects/<project-name>/architecture.md` for system overview and module map.

### 4. Query for specifics

kb query <project-name> "<natural language question>" --fmt json

See kb-search skill for full query options.

## Project name inference

If the project name is ambiguous, list `~/.scout/projects/` and find which indexed
project is an ancestor of the current working directory. If still ambiguous, ask the user.

## Error handling

- Ollama not running → inform user, suggest `ollama serve`
- Scout timeout → suggest `--timeout 600` or a smaller model
- No index but architecture.md exists → use architecture.md directly, skip kb query
```

### Notes

- Pi discovers skills automatically from `~/.pi/agent/skills/` — no registration needed.
- The skill references the `kb-search` skill for query detail — both load when relevant.

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
cd /path/to/scout
python3.11 -m pytest tests/test_compile.py -v
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