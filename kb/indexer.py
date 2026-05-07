"""Index a project into a local ChromaDB vector store.

Supports incremental re-indexing: chunk IDs are content-hash based
(see chunker.chunk_id), so only genuinely new or changed chunks are
re-embedded on subsequent runs.
"""

import math
import os
import chromadb

from utils import load_files
from chunker import chunk_file, chunk_id
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


def _chunk_hash(text: str) -> str:
    """Full 32-char hex hash for metadata. Chunk IDs are already 16-char hashes."""
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def _chunk_metadata(c: dict) -> dict:
    """Build ChromaDB metadata dict for a chunk."""
    return {
        "path": c["path"],
        "chunk": c["chunk_index"],
    }


def index_project(project_path: str) -> int:
    project_name = os.path.basename(project_path.rstrip("/"))

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
            metadatas=[_chunk_metadata(c) for c in batch]
        )
        stored += len(batch)

    _simple_bar(" Embedding", batch_count, batch_count, done=True)

    print(f"\n  {GREEN}{BOLD}Indexed {len(files)} files → {len(chunks)} chunks into '{project_name}' "
          f"({len(upsert_chunks)} embedded, {skipped} skipped){RESET}")
    return len(chunks)
