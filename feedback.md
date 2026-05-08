# Scout + KB — Reference Notes

## Pipeline Overview

Three stages, each building on the last:

```
repomix → scout → kb
snapshot   understand   search
```

| Stage | Output | Purpose |
|---|---|---|
| repomix | XML snapshot | Single dump of entire source tree |
| scout | `architecture.md`, `dependencies.json` | LLM-generated understanding of the codebase |
| kb | ChromaDB vector index | Semantic search over actual source chunks |

---

## The Silo Problem

The three outputs currently stay separate. When you ask *"how do tauri commands connect to the frontend"*, you get back raw chunk text with no architectural context — the LLM has to reconstruct the big picture from fragments.

**The natural next step** is a query layer that assembles a context package:

```
user question
    → embed → top-k chunks from ChromaDB
    → look up those file paths in dependencies.json → find their neighbours
    → prepend relevant section of architecture.md
    → send the whole thing to the model
```

This turns the toolchain from a code search tool into something closer to a local Cursor — the model gets both the precise relevant code *and* the architectural context to reason about it.

---

## Three Concrete Improvements

### 1. Richer dependency graph edges

`dependencies.json` is currently generated from `architecture.md`, which is already a lossy summary. The actual source lives in `kb` — run the import resolution from `compile.py`'s `_extract_refs` / `_resolve_ref` directly against the raw files to get a ground-truth graph. Use that to expand retrieval: fetch a chunk's neighbours in the import graph, not just its nearest semantic neighbours.

### 2. Index `architecture.md` into kb too

Right now it lives outside the vector store. If you embed it alongside source chunks, a query about architecture naturally surfaces the relevant section. Tag those chunks distinctly so you can weight or filter them:

```python
{"type": "architecture"}
```

### 3. Stable chunk IDs

Right now:
```python
chunk_id = f"{path}::chunk{i}"
```

If a function moves down the file, its index changes and ChromaDB treats it as a new document. A content hash gives you stable IDs, enables incremental re-indexing, and lets the dependency graph reference chunks by ID:

```python
import hashlib
chunk_id = f"{path}::{hashlib.sha256(text.encode()).hexdigest()[:16]}"
```

---

## Chunk Metadata Interface

Current metadata is too thin:

```python
{"path": c["path"], "chunk": c["chunk_index"]}
```

Extended interface:

```python
{
    "path":     c["path"],
    "chunk":    c["chunk_index"],
    "project":  project_name,
    "type":     c.get("type", "source"),     # "source" | "design-system" | "architecture"
    "category": c.get("category"),           # "token" | "pattern" | "guideline" | "component" | None
    "tags":     c.get("tags", []),           # ["color", "spacing", "motion", "typography"]
}
```

`category` is coarse — what kind of artifact is this.
`tags` is freeform — whatever the content actually covers.

### Example mappings

| File | category | tags |
|---|---|---|
| Color token file | `token` | `["color"]` |
| Animation spec | `token` | `["motion"]` |
| Button component | `component` | `["interactive", "form"]` |
| Writing style guide | `guideline` | `["copy", "tone"]` |
| Spacing pattern | `pattern` | `["layout", "spacing"]` |

### Filtering in ChromaDB

```python
collection.query(
    query_embeddings=[query_vec],
    where={"category": "token"},
    n_results=k,
)
```

This lets a Pi skill be specific — *"find me color tokens"* vs *"find me interaction patterns"* — rather than doing a broad search and hoping the right thing floats up.

---

## Design System Integration

### The workflow

1. `kb index` your design system repo with `--tag type=design-system`
2. Write a Pi skill / `AGENTS.md` entry:

```markdown
## Design System
This project uses a design system. Before writing any component or UI code,
run kb_search("design-system", "<component type>") to find the relevant
DS components. Always prefer DS primitives over custom implementations.
```

3. When Pi goes to write a `<Button>` or a form, the skill fires, `kb query` returns the actual DS component source + usage patterns, and the model writes against the real API rather than hallucinating props.

### Why DS works especially well with this approach

- **The model's training data is wrong** — it knows MUI, Radix, shadcn, but not *your* DS
- **Chunks are naturally well-bounded** — one component per file, clean function/export boundaries
- **Usage patterns are in the code** — existing app components that consume the DS are also indexed, so a search for "modal" returns both the DS `Modal` implementation *and* real usage examples in context

### Two-index pattern

Keep your DS as a separately named kb from your app code:

```bash
kb index ~/design-system --name my-ds
kb index ~/my-app        --name my-app
```

The skill queries `my-ds` first, falls back to `my-app` only if nothing relevant comes back. DS hits are never diluted by app code in the rankings, and you can update the DS index independently when it changes.

---

## Pi Integration

Pi is the right harness for wiring this together.

| Pi feature | How it maps |
|---|---|
| **Skills** | Expose `kb query` as a tool Pi calls mid-session |
| **AGENTS.md** | Drop `architecture.md` content here — Pi injects it at startup automatically |
| **Print mode** | `pi -p "query" --mode json` — pipe `kb query` output directly into a Pi invocation |

### Minimal skill shape

```markdown
## kb-search
Search the local code knowledge base.

Usage: kb query <project> "<question>" --fmt json

Call this before writing any component, implementing any feature, or
answering questions about how the codebase works.
```

Pi handles context window management, model switching, and session history — your tools stay as pure CLI utilities.

---

## Obsidian

No changes needed to the pipeline. `architecture.md` is already a valid Obsidian note — drop it into your vault and add `[[wikilinks]]` manually where you want to connect concepts to other notes.

### How they complement each other

| | Scout / KB | Obsidian wiki |
|---|---|---|
| **Captures** | What the code does | Why decisions were made |
| **Stays in sync** | Re-run the pipeline | Manual updates |
| **Scales to large repos** | Yes | Bottlenecked by writing time |
| **Survives codebase deletion** | No | Yes — it's your knowledge |
| **Tacit understanding** | No | Yes |

`architecture.md` is a first draft of the Obsidian overview page — the kind of note you'd write manually after understanding a new codebase. Annotate it with what the LLM couldn't know: team decisions, known bugs, historical context.