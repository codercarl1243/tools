"""
Structure-aware chunker.

Strategy per file type:
  .rs          → split on fn/impl/struct/enum/trait boundaries
  .ts/.tsx/.js/.jsx → split on function/component/class boundaries
  everything else   → overlapping sliding window

Falls back to sliding window whenever structural splitting
produces chunks that are too large (>1500 chars).
"""

import hashlib
import re

# Tuning knobs
WINDOW_SIZE = 800       # chars per sliding-window chunk
OVERLAP     = 150       # overlap between windows
MAX_CHUNK   = 1500      # if a structural chunk exceeds this, sub-split it


# ── Rust ──────────────────────────────────────────────────────────────────────

# Matches the start of any top-level Rust item.
# Handles stacked/multi-line attributes by greedily consuming consecutive
# #[...] blocks (including those spanning multiple lines) before the keyword.
_RS_BOUNDARY = re.compile(
    r"(?:^|\n)"                            # start of line
    r"(?:"                                  # group start
    r"(?:#\[[\s\S]*?\]\s*)*"            # zero or more attribute blocks (greedy across newlines)
    r"(?:pub(?:\s*\([^)]*\))?\s+)?"       # optional visibility
    r"(?:async\s+)?"                       # optional async
    r"(?:fn|impl|struct|enum|trait|type|mod|const|static|use)\b"
    r")"                                   # group end
    ,
    re.MULTILINE,
)

def _split_rust(content: str) -> list[str]:
    boundaries = [m.start() for m in _RS_BOUNDARY.finditer(content)]
    if len(boundaries) < 2:
        return _sliding_window(content)
    sections = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(content)
        sections.append(content[start:end].strip())
    return _flatten(sections)


# ── Python ───────────────────────────────────────────────────────────────────

_PY_BOUNDARY = re.compile(
    r"(?:^|\n)"
    r"(?:"
    r"(?:@\w[\w.]*(?:\([^)]*\))?\s*\n\s*)*"  # optional decorators
    r"(?:async\s+)?"
    r"(?:def|class)\s+\w+"
    r")",
    re.MULTILINE,
)

def _split_python(content: str) -> list[str]:
    boundaries = [m.start() for m in _PY_BOUNDARY.finditer(content)]
    if len(boundaries) < 2:
        return _sliding_window(content)
    sections = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(content)
        sections.append(content[start:end].strip())
    return _flatten(sections)


# ── TypeScript / React ────────────────────────────────────────────────────────

_TS_BOUNDARY = re.compile(
    r"(?:^|\n)"
    r"(?:"
    r"(?:export\s+(?:default\s+)?)?"    # optional export
    r"(?:async\s+)?"
    r"(?:"
    r"function\s+\w+"                    # function declaration
    r"|const\s+\w+\s*[=:]"              # const arrow fn / component
    r"|class\s+\w+"                      # class
    r"|interface\s+\w+"                  # interface
    r"|type\s+\w+\s*="                   # type alias
    r"|enum\s+\w+"                       # enum
    r")"
    r")",
    re.MULTILINE,
)

def _split_ts(content: str) -> list[str]:
    boundaries = [m.start() for m in _TS_BOUNDARY.finditer(content)]
    if len(boundaries) < 2:
        return _sliding_window(content)
    sections = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(content)
        sections.append(content[start:end].strip())
    return _flatten(sections)


# ── Sliding window (fallback) ─────────────────────────────────────────────────

def _sliding_window(content: str, size: int = WINDOW_SIZE, overlap: int = OVERLAP) -> list[str]:
    chunks = []
    start = 0
    while start < len(content):
        end = min(start + size, len(content))
        chunk = content[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(content):
            break
        start += size - overlap
    return chunks


# ── Sub-split oversized structural chunks ────────────────────────────────────

def _flatten(sections: list[str]) -> list[str]:
    """If a structural section is still too large, sub-split with sliding window."""
    out = []
    for s in sections:
        if not s:
            continue
        if len(s) > MAX_CHUNK:
            out.extend(_sliding_window(s))
        else:
            out.append(s)
    return out


# ── Public API ────────────────────────────────────────────────────────────────

def chunk_id(text: str) -> str:
    """Stable content-hash ID for a chunk (16-char hex)."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def chunk_file(file: dict) -> list[dict]:
    """
    Takes a file dict {path, content} and returns a list of chunk dicts:
      {id, text, path, chunk_index}

    Each chunk's text is prepended with a file-context header so that
    vector-store retrievals carry file-level context for the consuming LLM.

    Chunk IDs are content-based (SHA-256) so they stay stable across
    re-indexes unless the chunk content actually changes.
    """
    path    = file["path"]
    content = file["content"]
    ext     = path.rsplit(".", 1)[-1].lower()

    if ext == "rs":
        texts = _split_rust(content)
    elif ext in ("ts", "tsx", "js", "jsx"):
        texts = _split_ts(content)
    elif ext == "py":
        texts = _split_python(content)
    else:
        texts = _sliding_window(content)

    chunks = []
    header = f"// File: {path}\n"
    for i, text in enumerate(texts):
        if not text.strip():
            continue
        full_text = header + text.strip()
        chunks.append({
            "id":          chunk_id(full_text),
            "text":        full_text,
            "path":        path,
            "chunk_index": i,
        })
    return chunks
