import typer
from indexer import index_project
from query import query_project

app = typer.Typer(
    help=(
        "kb — local code knowledge base\n\n"
        "Indexes your source code into a local vector database so you can search it "
        "with natural language queries.\n\n"
        "How it works:\n\n"
        "  1. 'kb index' walks your project, splits every source file into focused "
        "chunks (by function/component boundaries for .rs and .ts/.tsx, sliding window "
        "for everything else), embeds each chunk using a local code-search model, and "
        "stores the result in ./data/<project-name>/.\n\n"
        "  2. 'kb query' embeds your question the same way, finds the most similar "
        "chunks by cosine similarity, and returns the actual source snippets ranked by relevance.\n\n"
        "Nothing leaves your machine. No API keys. The model and index live in ~/.cache "
        "and ./data/ respectively.\n\n"
        "Quick start:\n\n"
        "  kb index ~/projects/my-tauri-app\n\n"
        "  kb query my-tauri-app \"how do tauri commands connect to the frontend\""
    ),
    no_args_is_help=True,
)


@app.command()
def index(path: str = typer.Argument(..., help="Path to the project root")):
    """
    Index a project into the local vector store.

    Walks the project, skips node_modules/target/dist and lock files.
    Splits each source file into chunks at function and component boundaries,
    embeds them with a local model, and stores everything under
    ./data/<project-name>/. Re-runs are incremental — only new or changed
    files are re-embedded.
    """
    index_project(path)


@app.command()
def query(
    project: str = typer.Argument(..., help="Project name (basename of the indexed path)"),
    q: str       = typer.Argument(..., help="Natural language query"),
    k: int       = typer.Option(5,     help="Number of results to return"),
    fmt: str     = typer.Option("print", help="Output format: print | json"),
):
    """
    Search the index for a project.

    Finds the most relevant source chunks for your question and prints them
    ranked by similarity score. Use --fmt json to get structured output
    suitable for piping into an LLM.

    Example: kb query my-tauri-app "how is the auth token stored" --k 8
    """
    query_project(project, q, k=k, output=fmt)


if __name__ == "__main__":
    app()
