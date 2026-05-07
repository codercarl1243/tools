import json
from db import get_model, _get_client


def query_project(
    project_name: str,
    query: str,
    k: int = 5,
    output: str = "print",   # "print" | "json" | "raw"
) -> list[dict]:
    """
    Search the index for a project.

    Returns a list of result dicts:
      {rank, path, chunk, score, text}

    output="print"  → pretty-print to stdout (default, human readable)
    output="json"   → print as JSON (pipe-friendly, ready for LLM step)
    output="raw"    → return list silently (use programmatically)
    """
    model      = get_model()
    client     = _get_client(project_name)

    try:
        collection = client.get_collection(project_name)
    except Exception:
        print(f"No index found for '{project_name}'. Run: kb index <path>")
        return []

    query_vec = model.encode([query])[0].tolist()
    results   = collection.query(
        query_embeddings=[query_vec],
        n_results=k,
    )

    hits = []
    for i, (doc, meta, dist) in enumerate(zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ), 1):
        hits.append({
            "rank":  i,
            "path":  meta["path"],
            "chunk": meta["chunk"],
            "score": round(1 - dist, 4),   # cosine similarity, higher = better
            "text":  doc,
        })

    if output == "print":
        _pretty_print(query, hits)
    elif output == "json":
        print(json.dumps(hits, indent=2))

    return hits


def _pretty_print(query: str, hits: list[dict]):
    print(f"\n── Results for: {query!r} ──\n")
    for h in hits:
        print(f"[{h['rank']}] {h['path']}  (chunk {h['chunk']})  score={h['score']}")
        print("-" * 60)
        print(h["text"][:500])
        print()
