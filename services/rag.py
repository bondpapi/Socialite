
from __future__ import annotations
from typing import Any, Dict, List, Optional

from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.docstore.document import Document

import json
from pathlib import Path

_store: Optional[FAISS] = None


_embeddings = OpenAIEmbeddings(model="text-embedding-3-small")


def add_documents(docs: List[Dict[str, Any]]) -> int:
    """
    Add documents to the RAG store.

    docs: list of dicts with keys:
      - id: str (unique doc id)
      - text: str (content)
      - metadata: optional dict (e.g. {"city": "Vilnius", "type": "guide"})

    Returns:
      number of documents added
    """
    global _store

    if not docs:
        return 0

    lc_docs: List[Document] = []
    for d in docs:
        text = d.get("text") or ""
        if not text.strip():
            continue

        metadata = dict(d.get("metadata") or {})
        # keep id in metadata as well for later
        if "id" in d:
            metadata.setdefault("id", d["id"])

        lc_docs.append(
            Document(
                page_content=text,
                metadata=metadata,
            )
        )

    if not lc_docs:
        return 0

    if _store is None:
        _store = FAISS.from_documents(lc_docs, _embeddings)
    else:
        _store.add_documents(lc_docs)

    return len(lc_docs)


def reset_store() -> None:
    """
    Clear the in-memory vector store. Useful for tests / reloads.
    """
    global _store
    _store = None


def search_knowledge(
    query: str,
    *,
    city: Optional[str] = None,
    k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Semantic search over the RAG store.

    Args:
      query: user question or description, e.g. "romantic date ideas"
      city: optional city hint (e.g. "Vilnius"); if provided, we bias
            the query by appending "in <city>".
      k: max number of results

    Returns:
      list of dicts:
        {
          "id": str | None,
          "text": str,
          "score": float,
          "metadata": {...},
        }
    """
    if _store is None:
        return []

    cooked_query = f"{query} in {city}" if city else query

    docs_scores = _store.similarity_search_with_score(cooked_query, k=k)
    results: List[Dict[str, Any]] = []

    for doc, score in docs_scores:
        md = dict(doc.metadata or {})
        doc_id = md.pop("id", None)
        results.append(
            {
                "id": doc_id,
                "text": doc.page_content,
                "score": float(score),
                "metadata": md,
            }
        )

    return results

def load_from_jsonl(path: str) -> int:
    """
    Load docs from a JSONL file and add them to the RAG store.

    Returns:
      number of documents successfully added
    """
    p = Path(path)
    if not p.exists():
        return 0

    docs = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            docs.append(rec)

    return add_documents(docs)