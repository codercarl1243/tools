import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "typebox";

/** Minimal shell arg parser - respects double-quoted strings (handles spaces in paths). */
function parseArgs(input: string): string[] {
  const result: string[] = [];
  let i = 0;
  while (i < input.length) {
    // Skip whitespace
    if (input[i] === " " || input[i] === "\t") { i++; continue; }
    if (input[i] === '"') {
      // Quoted arg
      i++; // skip opening quote
      const start = i;
      while (i < input.length && input[i] !== '"') {
        if (input[i] === '\\' && i + 1 < input.length) i++; // skip escaped chars
        i++;
      }
      result.push(input.slice(start, i));
      i++; // skip closing quote
    } else {
      // Unquoted arg
      const start = i;
      while (i < input.length && input[i] !== " " && input[i] !== "\t") i++;
      result.push(input.slice(start, i));
    }
  }
  return result;
}

const SCOUT = `${process.env.HOME}/tools/scout/bin/scout`;
const KB    = `${process.env.HOME}/tools/kb/main.py`;
const PY    = "python3";

export default function (pi: ExtensionAPI) {

  // ── /scout command ──────────────────────────────────────────────────────────
  // Runs the full scout pipeline (repomix → Ollama → kb index) for a project.
  // Streams output directly to the terminal so the user sees the interactive
  // prompts from the scout bash script.

  pi.registerCommand("scout", {
    description: "Build or rebuild the knowledge base for a project. Usage: /scout <project-path> [--model <model>]",

    handler: async (args, ctx) => {
      if (!args?.trim()) {
        ctx.ui.notify(
          "Usage: /scout <project-path> [--model <model>]\n" +
          "Example: /scout ~/projects/my-tauri-app",
          "info"
        );
        return;
      }

      // Expand ~ manually since exec doesn't use a shell
      const expandedArgs = args.trim().replace(/^~/, process.env.HOME ?? "~");

      // Parse args respecting quoted paths (handles spaces in directory names)
      const parts = parseArgs(expandedArgs);

      ctx.ui.notify(`Starting scout for: ${parts[0]}`, "info");

      try {
        // Use pi.exec with stdio inherit so the interactive prompts
        // (Y/n questions, model picker) flow through to the terminal
        const result = await pi.exec(SCOUT, parts, {
          signal: ctx.signal ?? undefined,
        });

        if (result.code === 0) {
          ctx.ui.notify("Knowledge base built successfully.", "success");
        } else {
          ctx.ui.notify(
            `scout exited with code ${result.code}.\n${result.stderr || ""}`.trim(),
            "error"
          );
        }
      } catch (err: any) {
        if (err?.name === "AbortError") {
          ctx.ui.notify("scout cancelled.", "warning");
        } else {
          ctx.ui.notify(`scout error: ${err?.message ?? err}`, "error");
        }
      }
    },
  });

  // ── re-index tool ───────────────────────────────────────────────────────────
  // A tool the LLM can call when it detects the codebase has changed and the
  // index may be stale. Runs only the kb index step (fast - no LLM involved).

  pi.registerTool({
    name: "kb_reindex",
    label: "Re-index project",
    description:
      "Re-index a project's source files into the local vector store. " +
      "Call this when the user mentions they've made significant changes to the codebase " +
      "and search results feel stale or irrelevant. This only rebuilds the vector index - " +
      "it does NOT re-run the Ollama architecture compilation.",
    promptSnippet: "Re-index a project's source files when the codebase has changed",
    promptGuidelines: [
      "Use kb_reindex when the user says they've refactored, added features, or search results feel outdated.",
      "Do not use kb_reindex proactively - only when the user signals the index is stale.",
    ],

    parameters: Type.Object({
      project_path: Type.String({
        description: "Absolute path to the project root (e.g. /Users/you/projects/my-app)",
      }),
    }),

    async execute(_toolCallId, params, signal, onUpdate, _ctx) {
      const path = (params.project_path.replace(/^~/, process.env.HOME ?? "~") || "").trim().replace(/\/+$/, "");
      const projectName = path.split("/").filter(Boolean).pop() ?? path;

      onUpdate?.({
        content: [{ type: "text", text: `Re-indexing ${projectName} ...` }],
      });

      const result = await pi.exec(PY, [KB, "index", path], {
        signal: signal ?? undefined,
      });

      if (result.code !== 0) {
        throw new Error(result.stderr || `kb index exited with code ${result.code}`);
      }

      const summary = result.stdout.trim().split("\n").pop() ?? "Done";

      return {
        content: [{ type: "text", text: `Re-indexed ${projectName}. ${summary}` }],
        details: { project: projectName, output: result.stdout },
      };
    },
  });

  // ── session start notification ──────────────────────────────────────────────
  pi.on("session_start", async (_event, ctx) => {
    // Only show in interactive mode - skip in print/json/rpc
    if (!ctx.hasUI) return;

    ctx.ui.setStatus(
      "scout",
      "scout ready · /scout <path> to index · kb-search skill for queries"
    );

    // Clear the status after 8 seconds so it doesn't clutter the footer
    setTimeout(() => {
      ctx.ui.setStatus("scout", undefined);
    }, 8000);
  });
}

/**
# TODOS
 
## Project registry

Eventually we'll want:

{
  "my-tauri-app": "/Users/carl/projects/my-tauri-app"
}

Then:

agents stop guessing paths
reindexing becomes safer
querying becomes cleaner

## Answer synthesis mode

Eventually:

kb ask my-project "How does auth work?"

where:

retrieval happens
results go directly to Qwen
synthesised answer returned

That's the natural evolution.

 * 
 */