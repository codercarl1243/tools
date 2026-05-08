"""Index a project into a local ChromaDB vector store.

Supports incremental re-indexing: chunk IDs are content-hash based
(see chunker.chunk_id), so only genuinely new or changed chunks are
re-embedded on subsequent runs.
"""

import json
import math
import os
import chromadb

from utils import load_files
from chunker import chunk_file
from db import get_model, _get_client, BOLD, DIM, GREEN, YELLOW, RESET


# ── Progress bar ──

def _simple_bar(label: str, current: int, total: int, done: bool = False, width: int = 30):
    """Minimal terminal progress bar — no dependencies beyond print."""
    frac = current / total if total else 1
    filled = int(width * frac)
    bar = "█" * filled + "░" * (width - filled)
    flag = "✓" if done else " "
    pct = f"{frac * 100:4.1f}%"
    print(f"\r  {label}  {bar} {pct}  ({current}/{total})  {flag}", flush=True, end="")
    if done:
        print()


# ── Extension → language map ──

EXT_LANG_MAP = {
    ".rs": "rust", ".ts": "typescript", ".tsx": "react",
    ".js": "javascript", ".jsx": "react", ".py": "python",
    ".go": "go", ".c": "c", ".cpp": "cpp", ".h": "c",
    ".vue": "vue", ".svelte": "svelte", ".json": "config",
    ".yaml": "config", ".yml": "config", ".toml": "config",
}


def _chunk_metadata(c: dict, node_lookup: dict = None, file_deps: dict = None, tag: str = None) -> dict:
    """Build ChromaDB metadata dict for a chunk."""
    path = c["path"]
    meta = {
        "path": path,
        "chunk": c["chunk_index"],
    }

    # Language — prefer dep graph node type, fall back to extension
    if node_lookup and path in node_lookup:
        meta["language"] = node_lookup[path].get("type", "other")
    else:
        ext = os.path.splitext(path)[1].lower()
        meta["language"] = EXT_LANG_MAP.get(ext, "other")

    # Dependencies — only if dep graph available and file has outgoing edges
    if file_deps and path in file_deps:
        meta["dependencies"] = ",".join(file_deps[path])

    # Tag — if provided
    if tag is not None:
        meta["tag"] = tag

    return meta


def index_project(project_path: str, name: str = None, tag: str = None) -> int:
    project_name = name or os.path.basename(project_path.rstrip("/"))

    # ── Load dependency graph (optional, from scout) ──
    node_lookup = {}
    file_deps = {}
    scout_dir = os.path.expanduser(f"~/.scout/projects/{project_name}")
    deps_path = os.path.join(scout_dir, "dependencies.json")
    if os.path.exists(deps_path):
        with open(deps_path) as f:
            dep_graph = json.load(f)
        node_lookup = {n["id"]: n for n in dep_graph.get("nodes", [])}
        for edge in dep_graph.get("edges", []):
            file_deps.setdefault(edge["from"], []).append(edge["to"])

    # ── Phase 1: Load & chunk files ──
    print(f"\n  {BOLD}Loading files from {project_path}...{RESET}")
    files = load_files(project_path)
    if not files:
        print("  No indexable files found.")
        return 0

    print(f"\n  {DIM}Chunking files...{RESET}")
    chunks = []
    total = len(files)
    for i, f in enumerate(files, 1):
        _simple_bar(" Chunking", i, total)
        chunks.extend(chunk_file(f))

    if not chunks:
        print("  No chunks produced.")
        return 0

    # ── Phase 2: Open (or create) the ChromaDB collection ──
    model = get_model()
    client = _get_client(project_name)

    try:
        collection = client.get_collection(project_name)
    except (chromadb.errors.InvalidDimensionException, Exception):
        collection = client.create_collection(
            name=project_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ── Phase 3: Incremental upsert — skip unchanged chunks ──
    # Chunk IDs are content-hash based. A missing ID means new or changed content;
    # an existing ID means the content is identical — no secondary hash check needed.
    existing_ids = set()
    try:
        existing = collection.get()
        if existing and existing["ids"]:
            existing_ids.update(existing["ids"])
    except Exception:
        pass

    upsert_chunks = [c for c in chunks if c["id"] not in existing_ids]
    skipped = len(chunks) - len(upsert_chunks)

    if not upsert_chunks:
        print(f"\n  {GREEN}All {len(chunks)} chunks unchanged — nothing to do.{RESET}")
        return 0

    batch_count = math.ceil(len(upsert_chunks) / 64)
    print(f"  {DIM}{len(files)} files → {len(chunks)} chunks, "
          f"{len(upsert_chunks)} to embed, {skipped} skipped"
          f" → {batch_count} batch(es){RESET}\n")

    # ── Phase 4: Embed & store new/changed chunks ──
    BATCH = 64
    stored = 0
    for i in range(0, len(upsert_chunks), BATCH):
        batch = upsert_chunks[i : i + BATCH]
        texts = [c["text"] for c in batch]

        batch_num = i // BATCH + 1
        _simple_bar(" Embedding", batch_num, batch_count)

        embeds = model.encode(texts, show_progress_bar=False).tolist()

        collection.add(
            ids=[c["id"] for c in batch],
            embeddings=embeds,
            documents=[c["text"] for c in batch],
            metadatas=[_chunk_metadata(c, node_lookup=node_lookup, file_deps=file_deps, tag=tag) for c in batch]
        )
        stored += len(batch)

    _simple_bar(" Embedding", batch_count, batch_count, done=True)

    print(f"\n  {GREEN}{BOLD}Indexed {len(files)} files → {len(chunks)} chunks into '{project_name}' "
          f"({len(upsert_chunks)} embedded, {skipped} skipped){RESET}")
    return len(chunks)
