import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import math
import chromadb
from sentence_transformers import SentenceTransformer
from utils import load_files
from chunker import chunk_file

# ── Colours ────
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


# Load once — shared by anything that imports this module
_model = None

def get_model() -> SentenceTransformer:
    """Return a shared SentenceTransformer instance (lazy-loaded).

    NOTE: Not thread-safe — no locking around _model assignment.
    Fine for single-threaded CLI use. Add threading.Lock if
    indexer.py is ever called from multiple threads.
    """
    global _model
    if _model is None:
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _model


def _get_client(project_name: str) -> chromadb.PersistentClient:
    persist_path = os.path.join(os.path.dirname(__file__), "data", project_name)
    os.makedirs(persist_path, exist_ok=True)
    return chromadb.PersistentClient(path=persist_path)


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

    # ── Phase 2: Build / rebuild the ChromaDB collection ──
    model = get_model()
    client = _get_client(project_name)

    try:
        client.delete_collection(project_name)
    except Exception:
        pass

    collection = client.create_collection(
        name=project_name,
        metadata={"hnsw:space": "cosine"},
    )

    batch_count = math.ceil(len(chunks) / 64)
    print(f"  {DIM}{len(files)} files → {len(chunks)} chunks → {batch_count} embedding batch(es){RESET}\n")

    # ── Phase 3: Embed & store in batches ──
    BATCH = 64
    stored = 0
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i : i + BATCH]
        texts = [c["text"] for c in batch]

        # Embed
        batch_num = i // BATCH + 1
        _simple_bar(" Embedding", batch_num, batch_count)

        embeds = model.encode(texts, show_progress_bar=False).tolist()

        # Store
        collection.add(
            ids=[c["id"] for c in batch],
            embeddings=embeds,
            documents=[c["text"] for c in batch],
            metadatas=[
                {"path": c["path"], "chunk": c["chunk_index"]}
                for c in batch
            ],
        )
        stored += len(batch)

    _simple_bar(" Embedding", batch_count, batch_count, done=True)

    print(f"\n  {GREEN}{BOLD}Indexed {len(files)} files → {len(chunks)} chunks into '{project_name}'{RESET}")
    return len(chunks)
