"""Sentence-transformer embedder.

Wraps `sentence-transformers/all-MiniLM-L6-v2` (384-dim, ~90 MB, CPU
friendly). The model is loaded lazily behind a lock so multiple
consumers do not race on the first call.
"""
from __future__ import annotations

import threading
from typing import List, Optional

import numpy as np


DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_lock = threading.Lock()
_model = None


def _load(name: str = DEFAULT_MODEL):
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(name)
    return _model


class Embedder:
    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name

    def embed(self, texts: List[str],
              batch_size: int = 32) -> np.ndarray:
        model = _load(self.model_name)
        emb = model.encode(list(texts), batch_size=batch_size,
                           convert_to_numpy=True, normalize_embeddings=True)
        return emb.astype("float32")

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    @property
    def dim(self) -> int:
        model = _load(self.model_name)
        return model.get_sentence_embedding_dimension()
