# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A three-component pipeline that turns any codebase into a searchable, semantically indexed knowledge base — entirely offline, no API keys.

```
repomix (XML dump) → scout/compile.py (Ollama → architecture.md + dependencies.json) → kb (ChromaDB vector index)
```

## Commands

### Tests

```bash
# scout/compile.py pure-function tests
cd scout && python3 -m pytest tests/test_compile.py -v

# kb tests
cd kb && python3 -m pytest tests/ -v

# Run a single test
cd scout && python3 -m pytest tests/test_compile.py::TestChunkFiles::test_single_file -v
```

### Run the full pipeline

```bash
scout ~/projects/my-app                        # guided interactive run
scout ~/projects/my-app --model llama3.1:8b   # pick a different Ollama model
scout ~/projects/my-app --no-cache            # ignore cached chunk results
```

### kb index / query

```bash
python3 ~/tools/kb/main.py index ~/projects/my-app           # (re)index only
python3 ~/tools/kb/main.py query my-app "how does auth work"  # human-readable
python3 ~/tools/kb/main.py query my-app "auth flow" --fmt json --k 8  # JSON output
```

### compile.py directly

```bash
python3 scout/compile.py \
  --repomix ~/.scout/projects/my-app/_repomix_raw.xml \
  --output-dir ~/.scout/projects/my-app \
  --project-name my-app \
  --emit-deps   # ground-truth dep graph from imports instead of LLM
```

## Architecture

### scout (`scout/bin/scout`, `scout/compile.py`)

`bin/scout` is a bash orchestrator — handles arg parsing, Ollama preflight, model picker, and calls repomix → compile.py → kb in sequence with Y/n prompts.

`compile.py` is the Python core:
1. `parse_repomix()` — regex-parses the XML dump (avoids pyexpat); truncates files > 4000 chars
2. `chunk_files()` — groups files by directory, uses union-find to merge directories connected by imports (bounded to 2× `max_chars`), then size-splits oversized groups
3. Per-chunk Ollama calls produce partial architecture analyses, then pairwise `MERGE_PROMPT` merges reduce them to one `architecture.md`
4. `build_dependency_graph()` — deterministic import resolution (no LLM) producing `dependencies.json` when `--emit-deps` is passed; LLM-generated otherwise
5. Intermediate chunk results are cached in `.scout_cache/` so interrupted runs resume; cache is deleted on success unless `--keep-cache`

### kb (`kb/`)

- `main.py` — Typer CLI with `index` and `query` subcommands
- `chunker.py` — structure-aware splitting: Rust (`fn/impl/struct/enum/trait`), TS/JS (`function/const/class/interface/type/enum`), everything else sliding window (800 chars, 150 overlap). Chunks > 1500 chars are sub-split. Chunk IDs are SHA-256 of content for stable re-indexing.
- `indexer.py` — walks project files, chunks them, embeds with `sentence-transformers/all-MiniLM-L6-v2`, upserts into ChromaDB at `kb/data/<project-name>/`
- `query.py` — embeds query, cosine-similarity search, ranked output
- `utils.py` — file walker; two-pass file detection (known extensions + system MIME fallback)

### Output layout

All artifacts land in `~/.scout/projects/<project-name>/`:
- `architecture.md` — merged Ollama analysis
- `dependencies.json` — edge list (nodes, edges, meta)
- `_repomix_raw.xml` — raw dump (optional, can delete after indexing)

Vector index lives in `kb/data/<project-name>/`.

### Extensions / skills

- `extensions/scout.ts` — Claude Code extension wiring up the `/scout` command and `kb_reindex` tool
- `skills/kb-search/SKILL.md` — skill definition for semantic search over indexed projects; invoked via `kb query <project> "<question>" --fmt json`
