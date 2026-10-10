import os
import threading

import structlog

logger = structlog.get_logger(__name__)

class EmbeddingService:
    """
    Service for generating embeddings using local models.
    Lazy-loads sentence-transformers to save memory on startup.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._model = None
                cls._instance._model_name = os.environ.get("COMFY_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
                cls._instance._dimension = None
                cls._instance._model_lock = threading.Lock()
        return cls._instance

    def _get_model(self):
        """Lazy load the sentence transformer model."""
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    logger.info("loading_embedding_model", model=self._model_name)
                    try:
                        from sentence_transformers import SentenceTransformer
                        # Device usually defaults to CPU if no GPU is available, which is perfect for Ryzen 5300U
                        self._model = SentenceTransformer(self._model_name, device="cpu")
                        logger.info("embedding_model_loaded", model=self._model_name)
                        # Derive the dimension from the loaded model instead of a
                        # hardcoded constant — swapping the model (via
                        # COMFY_EMBEDDING_MODEL) used to leave the dimension stale,
                        # so similarity scores silently mismatched the DB column.
                        self._dimension = self._model.get_sentence_embedding_dimension()
                    except Exception as e:
                        logger.error("embedding_model_load_failed", error=str(e))
                        raise RuntimeError(f"Failed to load embedding model: {e}")
        return self._model

    def generate_embedding(self, text: str) -> list[float]:
        """
        Generate an embedding for the given text.
        """
        if not text or not text.strip():
            dim = self._dimension or 384
            return [0.0] * dim  # Return zero vector for empty text
            
        model = self._get_model()
        try:
            # Generate embedding
            embedding = model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            logger.error("embedding_generation_failed", error=str(e))
            raise RuntimeError(f"Failed to generate embedding: {e}")

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for a list of texts in batch.
        """
        if not texts:
            return []
            
        model = self._get_model()
        try:
            embeddings = model.encode(texts, convert_to_numpy=True)
            return embeddings.tolist()
        except Exception as e:
            logger.error("batch_embedding_generation_failed", error=str(e))
            raise RuntimeError(f"Failed to generate batch embeddings: {e}")

def get_embedding_service() -> EmbeddingService:
    """Dependency injection helper."""
    return EmbeddingService()
