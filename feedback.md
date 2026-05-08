# things to fix now
* _chunk_hash in indexer.py is now unused — chunk_id from chunker.py does the same job and is what's actually used for IDs. Safe to delete.

* indexer.py imports chunk_id from chunker but never calls it directly — it comes in on the chunk dict already. The import can be cleaned up.

* query.py still catches bare Exception on client.get_collection — worth tightening to chromadb.errors.NotFoundError or equivalent when you're ready, but not blocking.

# plan 

* _chunk_metadata in indexer.py is where you'll plug in the extended metadata for #3 — type, category, tags, project. It's already cleanly isolated for that purpose which is good foresight.

_infer_metadata(path, content) in chunker.py — conservative path-pattern classifier returning category and tags

Wire it into chunk_file() so every chunk dict carries the new fields

Update _chunk_metadata() in indexer.py to pass type, category, tags, project through to ChromaDB

Update query.py result dicts to surface the new fields in hits

---

## Obsidian

No changes needed to the pipeline. `architecture.md` is already a valid Obsidian note — drop it into your vault and add `[[wikilinks]]` manually where you want to connect concepts to other notes.

### How they complement each other

| | Scout / KB | Obsidian wiki |
|---|---|---|
| **Captures** | What the code does | Why decisions were made |
| **Stays in sync** | Re-run the pipeline | Manual updates |
| **Scales to large repos** | Yes | Bottlenecked by writing time |
| **Survives codebase deletion** | No | Yes — it's your knowledge |
| **Tacit understanding** | No | Yes |

`architecture.md` is a first draft of the Obsidian overview page — the kind of note you'd write manually after understanding a new codebase. Annotate it with what the LLM couldn't know: team decisions, known bugs, historical context.