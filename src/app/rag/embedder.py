"""Text embedder.

Two backends are supported. `sentence-transformers` is preferred when
it is installed; on the free-tier VM (no GPU, tight disk) it is left
out because it drags in `torch` and about two gigabytes of CUDA
wheels. When missing, the embedder falls back to ChromaDB's built-in
`DefaultEmbeddingFunction`, which runs the same
`sentence-transformers/all-MiniLM-L6-v2` model but through
`onnxruntime` - the only extra dependency (already required by
ChromaDB itself).

Both paths produce L2-normalised 384-dim vectors so the rest of the
retrieval stack is agnostic.
"""
from __future__ import annotations

import threading
from typing import List, Optional

import numpy as np

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384

_lock = threading.Lock()
_backend = None  # tuple (kind, model)


def _load(model_name: str):
    global _backend
    if _backend is not None:
        return _backend
    with _lock:
        if _backend is None:
            _backend = _init_backend(model_name)
    return _backend


def _init_backend(model_name: str):
    # Preferred: sentence-transformers with torch. On the VM this is not
    # installed - see src/vm/requirements.txt.
    try:
        from sentence_transformers import SentenceTransformer
        return ("st", SentenceTransformer(model_name))
    except Exception:
        pass
    # Fallback: ChromaDB's ONNX-backed default embedding function.
    from chromadb.utils.embedding_functions import (
        DefaultEmbeddingFunction,
    )
    return ("cdb", DefaultEmbeddingFunction())


def _normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (arr / norms).astype("float32")


class Embedder:
    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name

    def embed(self, texts: List[str],
              batch_size: int = 32) -> np.ndarray:
        kind, backend = _load(self.model_name)
        if kind == "st":
            emb = backend.encode(list(texts), batch_size=batch_size,
                                 convert_to_numpy=True,
                                 normalize_embeddings=True)
            return emb.astype("float32")
        vectors = backend(list(texts))
        arr = np.asarray(vectors, dtype="float32")
        return _normalize(arr)

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    @property
    def dim(self) -> int:
        kind, backend = _load(self.model_name)
        if kind == "st":
            try:
                return int(backend.get_sentence_embedding_dimension())
            except Exception:
                return EMBED_DIM
        return EMBED_DIM
