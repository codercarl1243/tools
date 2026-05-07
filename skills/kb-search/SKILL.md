---
name: kb-search
description: Search a locally indexed codebase using natural language queries. Use when the user asks questions about how their project works, where specific functionality lives, how components connect, or anything requiring understanding of the codebase structure. Requires the project to have been indexed with 'kb index' first.
---

# kb-search

Semantic search over a locally indexed codebase. Uses vector embeddings to find the most relevant source code chunks for any natural language question.

## How it works

The `kb` tool indexes source files into a local ChromaDB vector store. Each file is split at function and component boundaries, embedded with a code-search model, and stored locally. Queries are embedded the same way and matched by cosine similarity — so "how does authentication work" finds the actual auth code even if it doesn't use those exact words.

## Running a search

```bash
kb query <project-name> "<question>" --fmt json
```

- `<project-name>` is the **basename** of the project directory (e.g. if the project is at `~/projects/my-tauri-app`, the name is `my-tauri-app`)
- `--fmt json` returns structured results you can reason over
- `--k 8` returns more results (default is 5)

## Workflow

1. Run the query and receive JSON results
2. Each result has: `rank`, `path`, `chunk`, `score`, `text`
3. Read the highest-scoring chunks (higher score = more relevant). Score above 0.5 is usually a good hit, but use your judgement
4. If a chunk is truncated or you need more context, use the `read` tool on the `path` to see the full file
5. Synthesise your answer from the actual source code

## Example

User: "how do tauri commands connect to the React frontend?"

```bash
kb query my-tauri-app "tauri commands invoke frontend" --fmt json --k 8
```

Or for a general web app:

```bash
kb query my-web-app "how is the database connection pool managed" --fmt json --k 8
```

Then read the returned chunks. Look for:
- RPC/IPC handlers (e.g. `#[tauri::command]`, API routes, GraphQL resolvers) — these are the backend entry points
- Frontend callers (e.g. `invoke(`, `fetch()`, `useQuery`) — these are the triggers
- Cross-reference them to explain the full flow

## If the project hasn't been indexed

Tell the user to run:
```bash
scout ~/projects/<project-name>
```

Or just the index step:
```bash
kb index ~/projects/<project-name>
```

## If you need architectural context

Scout generates `architecture.md` and `dependencies.json` in `~/.scout/projects/<project-name>/`. Read them for a high-level map of the system.

```bash
# Check what scout has generated
ls ~/.scout/projects/<project-name>/

# Read the architecture overview
read ~/.scout/projects/<project-name>/architecture.md

# Read the dependency graph
read ~/.scout/projects/<project-name>/dependencies.json
```

(Use the `read` tool — not `cat`.)

## Tips

- Be specific in queries — "file upload handler function" finds more than "file handling"
- Run 2-3 queries from different angles if the first doesn't find what you need
- Use `--k 10` for broad architectural questions, `--k 3` for pinpointing a specific function
- If scores are all below 0.3, the concept may use different terminology — try synonyms
- kb is stack-agnostic — works with any language or framework that produces text-based source files