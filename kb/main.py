import argparse
import os
import sys
from indexer import index_project
from query import query_project
from db import _get_client


def cmd_index(args):
    index_project(args.path, name=args.name, tag=args.tag)


def cmd_query(args):
    query_project(args.project, args.q, k=args.k, output=args.fmt, tag=args.tag)


def cmd_list(args):
    module_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(module_dir, "data")

    if not os.path.exists(data_dir):
        print("No projects indexed yet.")
        return

    projects = sorted(p for p in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, p)))
    if not projects:
        print("No projects indexed yet.")
        return

    print(f"\n  {'Project':<30} {'Chunks':>8}  Scout artifacts")
    print(f"  {'─'*30} {'─'*8}  {'─'*16}")
    for name in projects:
        try:
            client = _get_client(name)
            collection = client.get_collection(name)
            count = collection.count()
        except Exception:
            count = "?"

        scout_dir = os.path.expanduser(f"~/.scout/projects/{name}")
        artifacts = []
        if os.path.exists(os.path.join(scout_dir, "architecture.md")):
            artifacts.append("architecture.md")
        if os.path.exists(os.path.join(scout_dir, "dependencies.json")):
            artifacts.append("deps.json")

        print(f"  {name:<30} {str(count):>8}  {', '.join(artifacts) or '–'}")
    print()


def main():
    parser = argparse.ArgumentParser(
        prog="kb",
        description="kb — local code knowledge base",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Index a project into the local vector store")
    p_index.add_argument("path", help="Path to the project root")
    p_index.add_argument("--name", "-n", default=None, help="Override project name")
    p_index.add_argument("--tag",  "-t", default=None, help="Tag to attach to all chunks")

    p_query = sub.add_parser("query", help="Search the index for a project")
    p_query.add_argument("project", help="Project name (basename of the indexed path)")
    p_query.add_argument("q",       help="Natural language query")
    p_query.add_argument("--k",   type=int, default=5,  help="Number of results to return")
    p_query.add_argument("--fmt", default="print",       help="Output format: print | json")
    p_query.add_argument("--tag", "-t", default=None,   help="Filter to chunks with this tag")

    sub.add_parser("list", help="List all indexed projects with chunk counts and scout artifacts")

    args = parser.parse_args()

    if args.command == "index":
        cmd_index(args)
    elif args.command == "query":
        cmd_query(args)
    elif args.command == "list":
        cmd_list(args)


if __name__ == "__main__":
    main()
