import mimetypes
import os

IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", "__pycache__",
    "target", ".next", ".svelte-kit", ".venv", "venv",
    "knowledge_base", "vector_index", ".pnpm-store",
}

SKIP_FILES = {
    "package-lock.json", "yarn.lock", "Cargo.lock", "pnpm-lock.yaml",
    "poetry.lock", "Gemfile.lock",
}

# MIME types we consider "text / source code" (catches unknown extensions)
TEXT_MIME_PREFIXES = (
    "text/",
    "application/json",
    "application/javascript",
    "application/typescript",
    "application/xml",
    "application/toml",
    "application/x-httpd-php",
    "application/x-sh",
    "application/x-shellscript",
    "application/xhtml+xml",
    "application/x-perl",
    "application/x-rust",
    "application/yaml",
    "application/graphql",
)

# Extensions that mimetypes doesn't always register — force-include them
# (system libmagic/mimetypes coverage varies wildly between macOS/Linux)
KNOWN_SOURCE_EXTS = {
    # Rust
    ".rs",
    # TypeScript / JavaScript
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    # Python
    ".py", ".pyi",
    # Web
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".vue", ".svelte", ".astro", ".swc", ".liquid",
    # Config / data (text-based only)
    ".json", ".jsonc", ".json5",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".xml", ".svg",
    # Docs / markup
    ".md", ".mdx", ".rst", ".txt",
    # Shell / scripts
    ".sh", ".bash", ".zsh", ".fish",
    # PHP / Ruby / Go
    ".php", ".rb", ".go",
    # SQL
    ".sql",
}


def _is_source_file(path: str) -> bool:
    """Decide whether a file is parseable source code.

    Two-pass check:
      1. If the extension is in KNOWN_SOURCE_EXTS, include it immediately.
      2. Otherwise, ask the system mimetypes database — if it reports a
         well-known text MIME type, include it.
      3. If neither fires, skip the file (binary, assets, etc.).
    """
    ext = os.path.splitext(path)[1].lower()

    # 1. Known list
    if ext in KNOWN_SOURCE_EXTS:
        return True

    # 2. System MIME database
    mime, _ = mimetypes.guess_type(path)
    if mime and mime.startswith(TEXT_MIME_PREFIXES):
        return True

    return False


def load_files(path: str) -> list[dict]:
    files = []
    for root, dirs, filenames in os.walk(path):
        dirs[:] = sorted([d for d in dirs if d not in IGNORE_DIRS])
        for fname in sorted(filenames):
            if fname in SKIP_FILES:
                continue
            if not _is_source_file(fname):
                continue
            full_path = os.path.join(root, fname)
            # Symlink safety
            if not os.path.isfile(full_path):
                continue
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                if content.strip():
                    files.append({"path": full_path, "content": content})
            except OSError:
                continue
    return files
