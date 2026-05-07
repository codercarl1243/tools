# tools — Local Code Knowledge Base

A three-step pipeline that turns any codebase into a searchable, semantically indexed knowledge base — entirely offline, no API keys.

## Architecture

```
┌──────────┐    XML      ┌──────────┐    architecture.md  ┌──────────┐
│  repomix │ ──────────► │  scout   │ ──────────────────► │   kb     │
│  (dump)  │             │(compile) │                     │ (index)  │
└──────────┘             └──────────┘                     └──────────┘
     node  run.js      bash+python3+ollama           python3  main.py
```

1. **repomix** — wraps the `repomix` npm package to produce a single XML snapshot of the entire source tree
2. **scout** — chunks the XML into manageable pieces and feeds each to a local Ollama model, then pairwise-merges the results into `architecture.md` and `dependencies.json`
3. **kb** — chunks source files at function/class boundaries, embeds them with `sentence-transformers/all-MiniLM-L6-v2`, and stores them in ChromaDB for semantic search

All processing happens on your machine. Nothing leaves.

## Setup

### Prerequisites

- **Node.js** (for `repomix`)
- **Python 3.11+** (for `kb` and `scout`)
- **Ollama** running locally on `http://localhost:11434`
  - Recommended model: `qwen2.5-coder:14b` (or pull your own)

### Install

```bash
# 1. Clone / download this repo
cd ~/tools

# 2. Install repomix
cd repomix npm install

# 3. Install kb dependencies
cd ../kb pip3 install -r requirements.txt

# 4. Add scout to PATH
cd ../scout bash install.sh

# 5. Reload your shell
source ~/.bashrc   # or source ~/.zshrc
```

## Usage

### Full pipeline

```bash
scout ~/projects/my-app
```

Walks you through three steps with Y/n prompts:
1. **Structural Dump** — `repomix` captures the source tree as XML
2. **Knowledge Compilation** — Ollama generates architecture docs
3. **Vector Index** — `kb` embeds chunks into ChromaDB

```bash
# Use a specific Ollama model
scout ~/projects/my-app --model llama3.1:8b
```

### Re-index only (fast, no LLM)

After refactoring or adding features, rebuild just the vector index:

```bash
python3 ~/tools/kb/main.py index ~/projects/my-app
```

### Search

```bash
# Human-readable output
python3 ~/tools/kb/main.py query my-app "how does authentication work"

# JSON output (pipe into an LLM)
python3 ~/tools/kb/main.py query my-app "how does authentication work" --fmt json --k 8
```

Each result includes rank, file path, chunk index, relevance score, and the source text.

### Rebuild everything

Just run `scout` again on the same project — it deletes and rebuilds from scratch.

### Resuming after a failure

The compilation step caches intermediate results in `.scout_cache/` inside the output directory. If it fails mid-way (e.g., Ollama connection drops), re-running `scout` will skip already-completed chunks and pick up right where it left off. Cache is automatically cleaned up on success.

```
# Force a clean re-run (ignores cache)
scout ~/projects/my-app --no-cache

# Keep cache files for debugging
scout ~/projects/my-app --keep-cache
```

## Output

All generated artifacts live in `~/.scout/projects/project-name/`:

| File | Description |
|--|--|
| `architecture.md` | AI-generated system overview, interfaces, and module groups |
| `dependencies.json` | Machine-readable dependency graph (nodes, edges, IPC commands) |
| `_repomix_raw.xml` | Raw XML dump from repomix (optional — can be deleted after indexing) |

The vector index itself lives in `~/tools/kb/data/project-name/`.

## kb — Detail

### How chunking works

`kb` uses structure-aware chunking to keep semantic meaning intact:

- **`.rs`** — splits on `fn`, `impl`, `struct`, `enum`, `trait` boundaries
- **`.ts`/`.tsx`/`.js`/`.jsx`** — splits on `function`, `const`, `class`, `interface`, `type`, `enum` boundaries
- **Everything else** — overlapping sliding window (800 chars, 150 char overlap)

Chunks exceeding 1500 chars are sub-split with the sliding window.

### File detection

`kb` doesn't hardcode a static list of extensions. It uses a two-pass approach:

1. **Known source extensions** — a large include list (`*.ts`, `*.rs`, `*.vue`, `*.yaml`, `.sql`, etc.)
2. **System MIME database** — for unknown extensions, asks Python's `mimetypess` module if it's a text type

This means new file types are automatically picked up if your OS knows about them, without needing to edit code.

## Project structure

```
tools/
├── kb/                 # Python vector index CLI
│   ├── main.py         # Typer app (index / query)
│   ├── indexer.py      # Chunk loading, embedding, ChromaDB upsert
│   ├── query.py        # Vector search + output formatting
│   ├── chunker.py      # Structure-aware file splitting
│   └── utils.py        # File walking + MIME detection
├── repomix/            # Node wrapper around repomix npm package
│   ├── package.json
│   └── run.js          # Thin wrapper (node run.js [args...])
└── scout/              # Bash orchestrator + Python compile step
    ├── bin/
    │   └── scout        # Main CLI (preflight, prompts, orchestration)
    ├── compile.py       # Ollama compilation (architecture + dependencies)
    └── install.sh       # Adds scout to ~/.local/bin
```

## Integration with Pi (AI coding agent)

`tools` ships with a Pi extension and skill (installed in `~/.pi/agent/`):

| Component | Purpose |
|--|-- |
| `/scout \` command | Run the full pipeline from within Pi |
| `kb_reindex` tool | Rebuild vector index when codebase changes |
| `kb-search` skill | Semantic search over indexed projects |

See `~/.pi/agent/extensions/scout.ts` and `~/.pi/agent/skills/kb-search/` for implementation.

## Notes

- **Ollama**: The compilation step (step 2) requires Ollama running. If Ollama isn't available, scout will still generate the XML dump and index, but `architecture.md` won't be created
- **Model choice**: Bigger models (14b+) give better architecture analysis. Smaller models (7b) are faster but less precise
