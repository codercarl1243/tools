"""Tests for kb/indexer.py metadata and indexing logic."""

from indexer import _chunk_metadata, EXT_LANG_MAP


class TestChunkMetadata:
    """Tests for _chunk_metadata with and without dep graph."""

    def _chunk(self, path, chunk_index=0):
        return {"path": path, "chunk_index": chunk_index, "id": "abc", "text": "x"}

    # ── Language from extension (no dep graph) ──

    def test_language_from_extension_ts(self):
        c = self._chunk("src/utils.ts")
        meta = _chunk_metadata(c)
        assert meta["language"] == "typescript"

    def test_language_from_extension_tsx(self):
        c = self._chunk("src/Button.tsx")
        meta = _chunk_metadata(c)
        assert meta["language"] == "react"

    def test_language_from_extension_rs(self):
        c = self._chunk("src/main.rs")
        meta = _chunk_metadata(c)
        assert meta["language"] == "rust"

    def test_language_from_extension_py(self):
        c = self._chunk("scripts/build.py")
        meta = _chunk_metadata(c)
        assert meta["language"] == "python"

    def test_language_unknown_extension(self):
        c = self._chunk("data/file.bin")
        meta = _chunk_metadata(c)
        assert meta["language"] == "other"

    def test_language_config_extensions(self):
        c = self._chunk("Cargo.toml")
        meta = _chunk_metadata(c)
        assert meta["language"] == "config"

    # ── Language from dep graph ──

    def test_language_from_dep_graph(self):
        node_lookup = {"src/main.rs": {"id": "src/main.rs", "type": "rust"}}
        c = self._chunk("src/main.rs")
        meta = _chunk_metadata(c, node_lookup=node_lookup)
        assert meta["language"] == "rust"

    def test_dep_graph_overrides_extension(self):
        """Dep graph type takes precedence over extension map."""
        node_lookup = {"src/file.ts": {"id": "src/file.ts", "type": "typescript"}}
        c = self._chunk("src/file.ts")
        meta = _chunk_metadata(c, node_lookup=node_lookup)
        assert meta["language"] == "typescript"

    def test_dep_graph_missing_path_falls_back_to_extension(self):
        """No KeyError when dep graph exists but file path isn't in it."""
        node_lookup = {"other.rs": {"id": "other.rs", "type": "rust"}}
        c = self._chunk("src/utils.ts")
        meta = _chunk_metadata(c, node_lookup=node_lookup)
        assert meta["language"] == "typescript"

    # ── Dependencies ──

    def test_dependencies_absent_when_no_edges(self):
        c = self._chunk("src/orphan.ts")
        meta = _chunk_metadata(c, file_deps={"src/other.ts": ["src/utils.ts"]})
        assert "dependencies" not in meta

    def test_dependencies_comma_separated(self):
        file_deps = {"src/Button.tsx": ["src/utils.ts", "src/theme.ts"]}
        c = self._chunk("src/Button.tsx")
        meta = _chunk_metadata(c, file_deps=file_deps)
        assert meta["dependencies"] == "src/utils.ts,src/theme.ts"

    def test_dependencies_absent_when_no_file_deps(self):
        c = self._chunk("src/Button.tsx")
        meta = _chunk_metadata(c)
        assert "dependencies" not in meta

    # ── Tag ──

    def test_tag_included_when_provided(self):
        c = self._chunk("src/utils.ts")
        meta = _chunk_metadata(c, tag="type=design-system")
        assert meta["tag"] == "type=design-system"

    def test_tag_absent_when_not_provided(self):
        c = self._chunk("src/utils.ts")
        meta = _chunk_metadata(c)
        assert "tag" not in meta

    # ── Core fields always present ──

    def test_core_fields_always_present(self):
        c = self._chunk("src/foo.rs", chunk_index=5)
        meta = _chunk_metadata(c)
        assert meta["path"] == "src/foo.rs"
        assert meta["chunk"] == 5
