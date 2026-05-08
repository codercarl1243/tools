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


def test_md_split_on_headings():
    from chunker import chunk_file
    content = "# Overview\n\nGeneral intro.\n\n## Module A\n\nDetails A.\n\n### Sub-topic\n\nNested.\n\n## Module B\n\nDetails B."
    chunks = chunk_file({"path": "doc.md", "content": content})
    assert len(chunks) == 4  # Overview, Module A, Sub-topic, Module B
    assert any("Overview" in c["text"] for c in chunks)
    assert any("Module A" in c["text"] for c in chunks)
    assert any("Module B" in c["text"] for c in chunks)


def test_md_single_heading_falls_back():
    from chunker import chunk_file
    content = "# Title\nSome paragraph text."
    chunks = chunk_file({"path": "doc.md", "content": content})
    assert len(chunks) >= 1


def test_architecture_md_virtual_path():
    from chunker import chunk_file
    content = "# Architecture\n\nProject overview."
    chunks = chunk_file({"path": ".scout/architecture.md", "content": content})
    assert all(c["path"] == ".scout/architecture.md" for c in chunks)


def test_architecture_md_multi_section():
    from chunker import chunk_file
    content = "# Project Architecture\n\nHigh level.\n\n## Module Map\n\nDetails.\n\n## Dependency Graph\n\nGraph details."
    chunks = chunk_file({"path": ".scout/architecture.md", "content": content})
    assert len(chunks) == 3
    assert all(c["path"] == ".scout/architecture.md" for c in chunks)


def test_indexer_loads_architecture_md():
    """index_project appends architecture.md when it exists."""
    import os
    from unittest.mock import patch, MagicMock
    from indexer import index_project

    scout_dir = os.path.expanduser("~/.scout/projects/test-arch")
    arch_path = os.path.join(scout_dir, "architecture.md")
    os.makedirs(scout_dir, exist_ok=True)
    try:
        with open(arch_path, "w") as f:
            f.write("# Architecture\n\nTest content.")
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": []}
        with patch("indexer.load_files", return_value=[{"path": "foo.txt", "content": "bar"}]), \
             patch("indexer._get_client") as mock_client_fn, \
             patch("indexer.get_model", return_value=MagicMock()), \
             patch("indexer.math.ceil", return_value=1):
            mock_client_fn.return_value.get_collection.side_effect = Exception("create")
            mock_client_fn.return_value.create_collection.return_value = mock_collection
            index_project("/tmp/test-arch", name="test-arch")
            add_calls = mock_collection.add.call_args_list
            all_paths = []
            for call in add_calls:
                for meta in call[1]["metadatas"]:
                    all_paths.append(meta["path"])
            assert ".scout/architecture.md" in all_paths
    finally:
        os.unlink(arch_path)
        os.rmdir(scout_dir)


def test_indexer_no_architecture_md():
    """index_project works when architecture.md does not exist."""
    from unittest.mock import patch, MagicMock
    from indexer import index_project

    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": []}
    with patch("indexer.load_files", return_value=[{"path": "foo.txt", "content": "bar"}]), \
         patch("indexer._get_client") as mock_client_fn, \
         patch("indexer.get_model", return_value=MagicMock()), \
         patch("indexer.math.ceil", return_value=1):
        mock_client_fn.return_value.get_collection.side_effect = Exception("create")
        mock_client_fn.return_value.create_collection.return_value = mock_collection
        index_project("/tmp/test-no-arch", name="test-no-arch")
        add_calls = mock_collection.add.call_args_list
        all_paths = []
        for call in add_calls:
            for meta in call[1]["metadatas"]:
                all_paths.append(meta["path"])
        assert ".scout/architecture.md" not in all_paths


def _make_file(content, suffix):
    """Write content to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path
