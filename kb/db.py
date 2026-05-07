"""Shared database and model helpers for the kb tool."""

import chromadb
from sentence_transformers import SentenceTransformer

# ── Colours ──
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


# ── Model ──

_model = None

def get_model() -> SentenceTransformer:
    """Return a shared SentenceTransformer instance (lazy-loaded).

    NOTE: Not thread-safe — no locking around _model assignment.
    Fine for single-threaded CLI use. Add threading.Lock if
    this module is ever called from multiple threads.
    """
    global _model
    if _model is None:
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _model


# ── ChromaDB client ──

def _get_client(project_name: str):
    import os
    import inspect
    # Resolve the persistent data path relative to this module’s data/ dir
    module_dir = os.path.dirname(inspect.getfile(inspect.currentframe()))
    persist_path = os.path.join(module_dir, "data", project_name)
    os.makedirs(persist_path, exist_ok=True)
    return chromadb.PersistentClient(path=persist_path)
