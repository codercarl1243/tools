"""Tests for kb/chunker.py chunk_id stability."""

import tempfile
import os
from chunker import chunk_file


def test_md_single_section_returns_as_is():
    """File with no structural boundaries uses sliding window."""
    content = "Just a plain paragraph with no headings."
    path = _make_file(content, ".md")
    try:
        chunks = chunk_file({"path": path, "content": content})
        assert len(chunks) >= 1
    finally:
        os.unlink(path)


def test_chunk_metadata_has_scout_architecture_path():
    """Virtual path .scout/architecture.md is preserved in chunks."""
    content = "# Architecture\n\nProject overview."
    chunks = chunk_file({"path": ".scout/architecture.md", "content": content})
    assert all(c["path"] == ".scout/architecture.md" for c in chunks)


def test_chunk_id_is_stable():
    """Same content produces same chunk_id."""
    from chunker import chunk_id
    text = "fn hello() { println!(\"hi\"); }"
    id1 = chunk_id("// File: src/lib.rs\n" + text)
    id2 = chunk_id("// File: src/lib.rs\n" + text)
    assert id1 == id2


def test_chunk_id_changes_on_rename():
    """Different path header produces different ID (renamed file)."""
    from chunker import chunk_id
    text = "fn hello() { println!(\"hi\"); }"
    id1 = chunk_id("// File: src/lib.rs\n" + text)
    id2 = chunk_id("// File: src/utils.rs\n" + text)
    assert id1 != id2


def _make_file(content, suffix):
    """Write content to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path
