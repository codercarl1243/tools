#!/usr/bin/env python3
"""
compile.py — Knowledge Compilation Step
Reads the repomix XML dump and uses a local Ollama model to generate:
  - architecture.md  (system overview, IPC boundary map, module groups)
  - dependencies.json (machine-readable file dependency graph)
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

# ── Colours ───────────────────────────────────────────────────────────────────
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
YELLOW = "\033[33m"
RED    = "\033[31m"
RESET  = "\033[0m"

def log(msg, color=DIM):
    print(f"  {color}{msg}{RESET}", flush=True)


# ── Ollama ────────────────────────────────────────────────────────────────────

def ollama(model: str, system: str, prompt: str) -> str:
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
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode()).get("response", "").strip()
    except urllib.error.URLError:
        print(f"\n{RED}Cannot reach Ollama. Is it running? Try: ollama serve{RESET}")
        sys.exit(1)


# ── Repomix XML parsing ───────────────────────────────────────────────────────

SKIP_FILES = {
    "package-lock.json", "yarn.lock", "Cargo.lock", "pnpm-lock.yaml",
}
SKIP_EXT = {".png", ".jpg", ".ico", ".woff", ".ttf", ".webp", ".lock"}

def parse_repomix(xml_path: Path) -> list[dict]:
    files = []
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        for elem in root.iter("file"):
            path = elem.get("path", "")
            content = (elem.text or "").strip()
            if not content:
                continue
            if any(path.endswith(e) for e in SKIP_EXT):
                continue
            if Path(path).name in SKIP_FILES:
                continue
            # Truncate very large files — the LLM needs the shape, not every line
            if len(content) > 4000:
                content = content[:4000] + "\n... [truncated]"
            files.append({"path": path, "content": content})
    except ET.ParseError:
        log("XML parse issue — falling back to regex", YELLOW)
        raw = xml_path.read_text(errors="replace")
        for m in re.finditer(r'<file path="([^"]+)">(.*?)</file>', raw, re.DOTALL):
            content = m.group(2).strip()
            if len(content) > 4000:
                content = content[:4000] + "\n... [truncated]"
            files.append({"path": m.group(1), "content": content})
    return files

def chunk_files(files: list[dict], max_chars: int = 24_000) -> list[list[dict]]:
    chunks, current, size = [], [], 0
    for f in files:
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

MERGE_PROMPT = """You have been given multiple partial architecture analyses of the same project "{project}",
each covering a different subset of files.

Merge them into one coherent architecture.md document with this structure:

## System Overview
(synthesise the overviews into one clear paragraph)

## Key Interfaces & Boundaries
(merge all boundary/interface tables, deduplicate, cross-reference callers found in other chunks)

## Module Groups
(merge the module groups into a clean final list of 5-10 groups, no duplicates)

---

Partial analyses to merge:
{analyses}
"""

DEP_PROMPT = """Based on this architecture document for project "{project}", extract a JSON dependency graph.

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

Architecture document:
{architecture}
"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repomix",      required=True, type=Path)
    parser.add_argument("--output-dir",   required=True, type=Path)
    parser.add_argument("--model",        default="qwen2.5-coder:14b")
    parser.add_argument("--project-name", default="project")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Parse
    log("Parsing repomix dump ...")
    files = parse_repomix(args.repomix)
    log(f"Found {len(files)} source files", GREEN)

    # 2. Architecture — chunk and analyse
    chunks = chunk_files(files)
    log(f"Processing {len(chunks)} chunk(s) through {args.model} ...")

    analyses = []
    for i, chunk in enumerate(chunks, 1):
        log(f"  Chunk {i}/{len(chunks)} ({len(chunk)} files) ...", CYAN)
        prompt = OVERVIEW_PROMPT.format(
            project=args.project_name,
            files=format_chunk(chunk),
        )
        result = ollama(args.model, SYSTEM, prompt)
        analyses.append(result)

    # 3. Merge if multiple chunks
    if len(analyses) == 1:
        architecture = analyses[0]
    else:
        log("  Merging analyses ...", CYAN)
        merge_prompt = MERGE_PROMPT.format(
            project=args.project_name,
            analyses="\n\n---CHUNK BOUNDARY---\n\n".join(analyses),
        )
        architecture = ollama(args.model, SYSTEM, merge_prompt)

    # 4. Write architecture.md
    arch_path = args.output_dir / "architecture.md"
    header = f"# {args.project_name} — Architecture\n\n> Generated by scout · Model: {args.model}\n\n---\n\n"
    arch_path.write_text(header + architecture, encoding="utf-8")
    log(f"architecture.md written ({len(architecture):,} chars)", GREEN)

    # 5. Generate dependencies.json
    log("  Generating dependency graph ...", CYAN)
    dep_raw = ollama(
        args.model,
        SYSTEM,
        DEP_PROMPT.format(
            project=args.project_name,
            architecture=architecture[:10_000],
        ),
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
    log("dependencies.json written", GREEN)


if __name__ == "__main__":
    main()
