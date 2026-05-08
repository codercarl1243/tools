#!/usr/bin/env python3
"""
compile.py — Knowledge Compilation Step
Reads the repomix XML dump and uses a local Ollama model to generate:
  - architecture.md  (system overview, IPC boundary map, module groups)
  - dependencies.json (machine-readable file dependency graph)
"""

import argparse
import json
import os
import re
import shutil
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

# ── Colours ───────────────────────────────────────────────────────────────────
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
YELLOW = "\033[33m"
RED    = "\033[31m"
RESET  = "\033[0m"

if sys.version_info < (3, 10):
    print(f"{RED}scout requires Python 3.10+ (found {sys.version_info.major}.{sys.version_info.minor}){RESET}")
    sys.exit(1)

def log(msg, color=DIM):
    print(f"  {color}{msg}{RESET}", flush=True)


# ── Ollama ────────────────────────────────────────────────────────────────────

def ollama(model: str, system: str, prompt: str, timeout: int = 300, label: str = "Ollama") -> str:
    payload = json.dumps({
        "model": model,
        "system": system,
        "prompt": prompt,
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
            result = body.get("response", "").strip()
            if not result:
                print(f"\n{RED}{label} returned an empty response. Retrying once...{RESET}", flush=True)
                with urllib.request.urlopen(req, timeout=timeout) as resp2:
                    body2 = json.loads(resp2.read().decode())
                    result = body2.get("response", "").strip()
                    if not result:
                        print(f"\n{RED}{label} returned empty response again. Check model output.{RESET}")
                        sys.exit(1)
            return result
    except urllib.error.URLError as e:
        if "timed out" in str(e).lower():
            print(f"\n{RED}{label} timed out after {timeout}s. The prompt may be too large for this model.\nTry a larger model or use --timeout / --merge-timeout to increase the limit.{RESET}")
        else:
            print(f"\n{RED}Cannot reach Ollama at http://localhost:11434. Is it running? Try: ollama serve{RESET}")
        sys.exit(1)


# ── Repomix XML parsing ───────────────────────────────────────────────────────

SKIP_FILES = {
    "package-lock.json", "yarn.lock", "Cargo.lock", "pnpm-lock.yaml",
}
SKIP_EXT = {".png", ".jpg", ".ico", ".woff", ".ttf", ".webp", ".lock"}

def parse_repomix(xml_path: Path, skip_ext=None, skip_files=None) -> list[dict]:
    """Parse repomix XML dump, filtering out binary/lock files."""
    if skip_ext is None:
        skip_ext = SKIP_EXT
    if skip_files is None:
        skip_files = SKIP_FILES
    # Use regex-based parsing to avoid pyexpat compatibility issues
    # (e.g. Python 3.14 on macOS has a broken libexpat linkage)
    raw = xml_path.read_text(errors="replace")
    files = []
    for m in re.finditer(r'<file path="([^"]+)">(.*?)</file>', raw, re.DOTALL):
        path = m.group(1)
        content = m.group(2).strip()
        if not content:
            continue
        if any(path.endswith(e) for e in skip_ext):
            continue
        if Path(path).name in skip_files:
            continue
        if len(content) > 4000:
            content = content[:4000] + "\n... [truncated]"
        files.append({"path": path, "content": content})
    return files

# IPC / route command patterns per language extension
IPC_PATTERNS = {
    frozenset({".rs"}): [
        r"#\[tauri::command\][\s\S]{0,100}?fn\s+(\w+)",
    ],
    frozenset({".ts", ".tsx", ".js", ".jsx"}): [
        r"ipcMain\.(?:handle|on)\(['\"]([^'\"]+)['\"]",
        r"(?:app|router)\.(?:get|post|put|patch|delete)\(['\"]([^'\"]+)['\"]",
        r"(?:socket|io)\.on\(['\"]([^'\"]+)['\"]",
    ],
    frozenset({".py"}): [
        r"@(?:app|router)\.(?:get|post|put|patch|delete)\(['\"]([^'\"]+)['\"]",
    ],
}


def extract_ipc_commands(files: list[dict]) -> list[str]:
    """Extract IPC command and route names from source files via regex."""
    found = set()
    for f in files:
        ext = Path(f["path"]).suffix.lower()
        for key, patterns in IPC_PATTERNS.items():
            if ext in key:
                for pat in patterns:
                    for m in re.finditer(pat, f["content"], re.DOTALL):
                        name = m.group(1).strip()
                        if name:
                            found.add(name)
                break
    return sorted(found)


# Import patterns per language extension
IMPORT_PATTERNS = {
    # JavaScript / TypeScript
    frozenset({".ts", ".tsx", ".js", ".jsx"}):
        [r"from\s+['\"](.+?)['\"]" , r"require\(['\"](.+?)['\"]\)" ],
    # Rust
    frozenset({".rs"}):
        [r"use\s+super::([\w]+)" , r"mod\s+([\w]+)" ],
    # Python
    frozenset({".py"}):
        [r"from\s+(\S+)\s+import" , r"import\s+(\w+)" ],
    # Go
    frozenset({".go"}):
        [r"import\s+[\"()](\S+)[\"]" ],
    # C / C++ / Objective-C
    frozenset({".c", ".h", ".cpp", ".hpp", ".cc", ".hh"}):
        [r'#include\s+"(.+?)"'],
}


def _ext_key(path: str) -> frozenset:
    """Return the IMPORT_PATTERNS key for a file's extension."""
    ext = Path(path).suffix.lower()
    for key in IMPORT_PATTERNS:
        if ext in key:
            return key
    return None


def _extract_refs(content: str, file_path: str) -> set:
    """Extract module references from file content."""
    key = _ext_key(file_path)
    if not key:
        return set()
    patterns = IMPORT_PATTERNS[key]
    refs = set()
    for pat in patterns:
        for m in re.finditer(pat, content):
            refs.add(m.group(1))
    return refs


def _normalize(p: str) -> str:
    """Normalize a path (collapse ../ etc) without making it absolute."""
    return os.path.normpath(p)


def _resolve_ref(ref: str, file_path: str, all_normalized_paths: set) -> Optional[str]:
    """
    Try to resolve a module reference to an actual file path.
    Returns the matched (normalized) path or None.
    """
    base_dir = Path(file_path).parent
    # Try direct match first
    norm_ref = _normalize(ref)
    if norm_ref in all_normalized_paths:
        return norm_ref
    # Try relative resolution by replacing the extension
    for ext in ["", ".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".go", ".c", ".cpp", ".h", ".hpp"]:
        candidate = _normalize(str(base_dir / Path(ref).with_suffix(ext)))
        if candidate in all_normalized_paths:
            return candidate
    # Try appending extension (handles refs like './foo.type' -> 'foo.type.ts')
    resolved_ref = str(base_dir / ref)
    for ext in [".ts", ".tsx", ".js", ".jsx", ".py", ".rs"]:
        candidate = _normalize(resolved_ref + ext)
        if candidate in all_normalized_paths:
            return candidate
    # Try index files (e.g. import './foo' -> foo/index.ts)
    ref_path = Path(ref)
    if not ref_path.suffix:  # no extension, might be a directory
        for ext in [".ts", ".tsx", ".js", ".jsx", ".py", ".rs"]:
            candidate = _normalize(str(base_dir / ref_path / f"index{ext}"))
            if candidate in all_normalized_paths:
                return candidate
    return None


def chunk_files(files: list[dict], max_chars: int = 24_000) -> list[list[dict]]:
    """
    Smart chunking:
    1. Group files by directory
    2. Merge sibling groups that import each other
    3. Split oversized groups using fallback size-based splitting
    """
    if not files:
        return []

    all_paths = {_normalize(f["path"]) for f in files}
    path_to_file = {_normalize(f["path"]): f for f in files}

    # 1. Group by directory
    dir_groups: dict[str, list[dict]] = {}
    for f in files:
        dirkey = str(Path(f["path"]).parent)
        dir_groups.setdefault(dirkey, []).append(f)

    # 2. Build cross-reference edges between directories
    dir_refs: dict[str, set[str]] = {d: set() for d in dir_groups}
    for f in files:
        refs = _extract_refs(f["content"], f["path"])
        if not refs:
            continue
        src_dir = str(Path(f["path"]).parent)
        for ref in refs:
            resolved = _resolve_ref(ref, f["path"], all_paths)
            if resolved:
                target_dir = str(Path(resolved).parent)
                if target_dir != src_dir:
                    dir_refs[src_dir].add(target_dir)
                    dir_refs[target_dir].add(src_dir)

    # 3. Merge directories connected by imports (union-find)
    parent: dict[str, str] = {d: d for d in dir_groups}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Track merged sizes to avoid creating unbounded chunks
    group_sizes: dict[str, int] = {d: sum(len(f["path"]) + len(f["content"]) for f in files_in_dir)
                                   for d, files_in_dir in dir_groups.items()}

    for src_dir, targets in dir_refs.items():
        for target_dir in targets:
            if target_dir in parent:
                root_a, root_b = find(src_dir), find(target_dir)
                if root_a != root_b:
                    # Only merge if combined size stays under 2x the limit
                    combined = group_sizes[root_a] + group_sizes[root_b]
                    if combined <= max_chars * 2:
                        parent[root_a] = root_b
                        group_sizes[root_b] = combined

    # 4. Collect merged groups
    merged_groups: dict[str, list[dict]] = {}
    for d, files_in_dir in dir_groups.items():
        root = find(d)
        merged_groups.setdefault(root, []).extend(files_in_dir)

    # 5. Sort files within each group by path (deterministic order)
    for group in merged_groups.values():
        group.sort(key=lambda f: f["path"])

    # 6. Split oversized groups (enforced cap even after merge)
    chunks = []
    for group in merged_groups.values():
        group_size = sum(len(f["path"]) + len(f["content"]) for f in group)
        if group_size <= max_chars:
            chunks.append(group)
        else:
            # Fallback to simple size-based splitting
            current, size = [], 0
            for f in group:
                entry = len(f["path"]) + len(f["content"])
                if current and size + entry > max_chars:
                    chunks.append(current)
                    current, size = [], 0
                current.append(f)
                size += entry
            if current:
                chunks.append(current)
    return chunks

def format_chunk(files: list[dict]) -> str:
    return "\n\n".join(f"### {f['path']}\n{f['content']}" for f in files)


# ── Prompts ───────────────────────────────────────────────────────────────────

SYSTEM = """You are a senior software architect.
You read source code and produce precise, structured technical documentation.
Only describe what you can directly observe in the provided code. Never hallucinate."""

OVERVIEW_PROMPT = """Analyse these source files from a project called "{project}".

Produce a technical overview in this exact Markdown structure:

## System Overview
One paragraph. What this application does, the tech stack,
and the dominant architectural pattern you can observe.

## Key Interfaces & Boundaries
Identify the main communication channels, API routes, IPC commands,
module boundaries, or framework entry points you can observe.
Describe each one with one sentence.

If this is a frontend/backend app, clearly mark the boundary between them.
Format as a table where applicable:
| Component | File | Purpose |
|--|--|--  |

## Module Groups
Group the files into 5-10 logical modules (not file-by-file — think in terms of
responsibility). For each group:
**Group Name**
Purpose: one sentence.
Files: list the key files.

---

Source files:
{files}
"""

MERGE_PROMPT = """You have been given two partial architecture analyses of the same project "{project}",
each covering a different subset of files.

Merge them into one coherent architecture document with this structure:

## System Overview
(synthesise the overviews into one clear paragraph)

## Key Interfaces & Boundaries
(merge all boundary/interface tables, deduplicate, cross-reference callers found in other chunks)

## Module Groups
(merge the module groups into a clean final list of 5-10 groups, no duplicates)

---

Partial analysis A:
{analysis_a}

---

Partial analysis B:
{analysis_b}
"""

_DEP_PROMPT_BASE = """Based on this architecture document for project "{project}", extract a JSON dependency graph.

Return ONLY valid JSON — no markdown fences, no explanation, nothing else.

{{
  "nodes": [
    {{"id": "src/main.rs", "type": "rust|react|config|other", "label": "one sentence description"}}
  ],
  "edges": [
    {{"from": "src/main.rs", "to": "src/commands.rs", "kind": "imports|invokes|configures"}}
  ],
  "meta": {{
    "project": "{project}",
    "ipc_commands": ["command_name_1", "command_name_2"]
  }}
}}
{ipc_anchor}
Architecture document:
{architecture}
"""

_IPC_ANCHOR = """
The following IPC commands/routes were detected directly from source — use these exactly \
as the ipc_commands list. Do not add or remove any:
{commands}
"""


def build_dep_prompt(project: str, architecture: str, static_ipc: list[str]) -> str:
    anchor = _IPC_ANCHOR.format(commands="\n".join(f"- {c}" for c in static_ipc)) if static_ipc else ""
    return _DEP_PROMPT_BASE.format(project=project, architecture=architecture, ipc_anchor=anchor)


# Node type labels by extension
NODE_TYPE_MAP = {
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "react",
    ".js": "javascript",
    ".jsx": "react",
    ".py": "python",
    ".go": "go",
    ".c": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".h": "c",
    ".vue": "vue",
    ".svelte": "svelte",
    ".css": "stylesheet",
    ".scss": "stylesheet",
    ".html": "html",
    ".json": "config",
    ".yaml": "config",
    ".yml": "config",
    ".toml": "config",
}


def build_dependency_graph(files: list[dict], project_name: str) -> dict:
    """Build a ground-truth dependency graph from import resolution.

    Runs _extract_refs / _resolve_ref over every file and produces a
    deterministic edge list. No LLM involved — structural only.

    Returns a dict in the same schema as the LLM-generated dependencies.json:
      {nodes, edges, meta}
    """
    all_paths = {_normalize(f["path"]) for f in files}
    nodes = {}
    edges = set()  # use set for dedup, convert to list later
    unresolved = []  # refs that couldn't be resolved (local modules only)

    for f in files:
        path = _normalize(f["path"])
        # Register node (first seen type wins)
        if path not in nodes:
            ext = Path(path).suffix.lower()
            nodes[path] = {
                "id": path,
                "type": NODE_TYPE_MAP.get(ext, "other"),
                "parseable": _ext_key(path) is not None,
            }

        # Resolve imports
        refs = _extract_refs(f["content"], f["path"])
        for ref in refs:
            resolved = _resolve_ref(ref, f["path"], all_paths)
            if resolved:
                target = _normalize(resolved)
                edges.add((path, target))
            elif ref.startswith(".") or ref.startswith("/"):
                unresolved.append({"from": path, "ref": ref})

    dep_graph = {
        "nodes": list(nodes.values()),
        "edges": [
            {"from": src, "to": dst, "kind": "imports"}
            for src, dst in sorted(edges)
        ],
        "meta": {
            "project": project_name,
            "ipc_commands": [],
            "unresolved_refs": unresolved,
        },
    }
    return dep_graph


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repomix",      required=True, type=Path)
    parser.add_argument("--output-dir",   required=True, type=Path)
    parser.add_argument("--model",        default="qwen2.5-coder:14b")
    parser.add_argument("--project-name", default="project")
    parser.add_argument("--timeout",          type=int, default=300, help="Timeout in seconds per chunk Ollama request (default: 300)")
    parser.add_argument("--merge-timeout",    type=int, default=None, help="Timeout for merge/dep requests (default: 2x --timeout)")
    parser.add_argument("--no-cache",         action="store_true", help="Re-run all chunks from scratch")
    parser.add_argument("--keep-cache",       action="store_true", help="Keep .scout_cache after success")
    parser.add_argument("--include-ext",      action="append", default=[], help="Override skip: include files with this extension (may be repeated)")
    parser.add_argument("--include-file",     action="append", default=[], help="Override skip: include this filename (may be repeated)")
    parser.add_argument("--llm-deps",        action="store_true", help="Generate dependencies.json using LLM instead of source import resolution (slower, less reliable)")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    merge_timeout = args.merge_timeout or args.timeout * 2

    # 1. Parse
    log("Parsing repomix dump ...")
    effective_skip_ext = SKIP_EXT - set(args.include_ext)
    effective_skip_files = SKIP_FILES - set(args.include_file)
    files = parse_repomix(args.repomix, skip_ext=effective_skip_ext, skip_files=effective_skip_files)
    log(f"Found {len(files)} source files", GREEN)

    # 2. Architecture — chunk and analyse
    chunks = chunk_files(files)
    log(f"Processed {len(chunks)} chunk(s) from {len(files)} files")
    for i, c in enumerate(chunks):
        dirs = sorted(set(str(Path(f["path"]).parent) for f in c))
        log(f"  Chunk {i+1}: {len(c)} files — {', '.join(dirs)}", DIM)
    log(f"Processing {len(chunks)} chunk(s) through {args.model} ..")

    # Cache dir for intermediate results (so re-runs skip completed chunks)
    cache_dir = args.output_dir / ".scout_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    use_cache = not args.no_cache

    analyses = []
    for i, chunk in enumerate(chunks, 1):
        cache_file = cache_dir / f"analysis_{i:02d}.md"
        if use_cache and cache_file.exists():
            log(f"  Chunk {i}/{len(chunks)} — cached, skipping", GREEN)
            analyses.append(cache_file.read_text(encoding="utf-8"))
            continue
        log(f"  Chunk {i}/{len(chunks)} ({len(chunk)} files) ...", CYAN)
        prompt = OVERVIEW_PROMPT.format(
            project=args.project_name,
            files=format_chunk(chunk),
        )
        result = ollama(args.model, SYSTEM, prompt, timeout=args.timeout, label=f"Chunk {i}/{len(chunks)}")
        cache_file.write_text(result, encoding="utf-8")
        analyses.append(result)

    # 3. Merge incrementally (pairwise, two at a time) if multiple chunks
    if len(analyses) == 1:
        architecture = analyses[0]
    else:
        cache_dir = args.output_dir / ".scout_cache"
        merged = analyses[0]
        for i in range(1, len(analyses)):
            merge_cache = cache_dir / f"merge_{i:02d}.md"
            if use_cache and merge_cache.exists():
                log(f"  Merge ({i}/{len(analyses)-1}) — cached, skipping", GREEN)
                merged = merge_cache.read_text(encoding="utf-8")
                continue
            log(f"  Merging ({i}/{len(analyses)-1}) ...", CYAN)
            merge_prompt = MERGE_PROMPT.format(
                project=args.project_name,
                analysis_a=merged,
                analysis_b=analyses[i],
            )
            merged = ollama(args.model, SYSTEM, merge_prompt, timeout=merge_timeout, label=f"Merge {i}/{len(analyses)-1}")
            merge_cache.write_text(merged, encoding="utf-8")
        architecture = merged

    # 4. Write architecture.md
    arch_path = args.output_dir / "architecture.md"
    header = f"# {args.project_name} — Architecture\n\n> Generated by scout · Model: {args.model}\n\n---\n\n"
    arch_path.write_text(header + architecture, encoding="utf-8")
    log(f"architecture.md written ({len(architecture):,} chars)", GREEN)

    # 5. Generate dependencies.json
    static_ipc = extract_ipc_commands(files)
    if static_ipc:
        log(f"  Detected {len(static_ipc)} IPC command(s): {', '.join(static_ipc)}", GREEN)

    if not args.llm_deps:
        log("  Building dependency graph from source ...", CYAN)
        dep_data = build_dependency_graph(files, args.project_name)
        dep_data["meta"]["ipc_commands"] = static_ipc
    else:
        dep_input = architecture[:10_000]
        if len(architecture) > 10_000:
            log(f"  Note: architecture truncated to 10,000 chars for dependency graph (original: {len(architecture):,} chars)", YELLOW)
        log("  Generating dependency graph ...", CYAN)
        dep_raw = ollama(
            args.model,
            SYSTEM,
            build_dep_prompt(args.project_name, dep_input, static_ipc),
            timeout=merge_timeout,
            label="Dependency graph",
        )

        # Strip any accidental markdown fences
        dep_clean = re.sub(r"```(?:json)?\n?", "", dep_raw).strip().rstrip("`").strip()

        try:
            dep_data = json.loads(dep_clean)
        except json.JSONDecodeError:
            log("Could not parse dependency JSON — saving raw output", YELLOW)
            dep_data = {"raw": dep_raw, "parse_error": True}

    dep_path = args.output_dir / "dependencies.json"
    dep_path.write_text(json.dumps(dep_data, indent=2), encoding="utf-8")
    edge_count = len(dep_data.get("edges", []))
    node_count = len(dep_data.get("nodes", []))
    log(f"dependencies.json written ({node_count} nodes, {edge_count} edges)", GREEN)

    # Clean up cache unless --keep-cache
    if not args.keep_cache:
        cache_path = args.output_dir / ".scout_cache"
        if cache_path.exists():
            shutil.rmtree(cache_path)
            log("Cache cleaned up", DIM)


if __name__ == "__main__":
    main()
