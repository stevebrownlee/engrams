# src/engrams/core/embedding_service.py
import logging
import threading
from typing import List, Optional

from chromadb.utils import embedding_functions  # Added for Chroma EmbeddingFunction
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

# Global variable to hold the loaded model, and a lock for thread-safe initialization
_model: Optional[SentenceTransformer] = None
_model_lock = threading.Lock()
# Specify the model name from research (Design Doc ID 23)
DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"


def _load_model(model_name: str = DEFAULT_MODEL_NAME) -> SentenceTransformer:
    """
    Loads the Sentence Transformer model.
    This function is intended to be called internally, ideally once.
    """
    global _model
    # Double-check locking pattern for thread-safe lazy initialization
    if _model is None:
        with _model_lock:
            if _model is None:
                log.info(f"Loading Sentence Transformer model: {model_name}...")
                try:
                    _model = SentenceTransformer(model_name)
                    log.info(
                        f"Sentence Transformer model '{model_name}' loaded successfully."
                    )
                except Exception as e:
                    log.error(
                        f"Failed to load Sentence Transformer model '{model_name}': {e}",
                        exc_info=True,
                    )
                    # Depending on policy, could raise or return None and let caller handle
                    raise  # Re-raise to make failure explicit
    if _model is None:  # Should not happen if raise is used above, but as a safeguard
        raise RuntimeError(f"Model '{model_name}' could not be loaded.")
    return _model


def get_embedding(text: str, model_name: str = DEFAULT_MODEL_NAME) -> List[float]:
    """
    Generates an embedding for the given text using the specified Sentence Transformer model.
    The model is loaded on the first call.

    Args:
        text: The input text to embed.
        model_name: The name of the Sentence Transformer model to use.

    Returns:
        A list of floats representing the embedding vector.

    Raises:
        RuntimeError: If the model cannot be loaded or embedding fails.
    """
    model = _load_model(model_name)
    try:
        log.debug(
            f"Generating embedding for text snippet (first 50 chars): '{text[:50]}...'"
        )
        embedding = model.encode(text, convert_to_tensor=False)  # Returns numpy array
        # Ensure it's a standard list of floats for broader compatibility (e.g., JSON serialization)
        return embedding.tolist()
    except Exception as e:
        log.error(f"Failed to generate embedding for text: {e}", exc_info=True)
        raise RuntimeError(f"Embedding generation failed: {e}")


def get_chroma_embedding_function(
    model_name: str = DEFAULT_MODEL_NAME,
) -> embedding_functions.SentenceTransformerEmbeddingFunction:
    """
    Returns a ChromaDB-compatible SentenceTransformerEmbeddingFunction instance
    initialized with the specified model name.

    Args:
        model_name: The name of the Sentence Transformer model to use.

    Returns:
        An instance of chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction.

    Raises:
        ImportError: If chromadb is not installed or SentenceTransformerEmbeddingFunction cannot be imported.
        Exception: Potentially from SentenceTransformerEmbeddingFunction initialization if model is problematic,
                   though it usually loads lazily.
    """
    log.info(
        f"Creating Chroma SentenceTransformerEmbeddingFunction for model: {model_name}"
    )
    try:
        # Note: The SentenceTransformerEmbeddingFunction itself handles model loading internally.
        # We are just configuring it with the model name.
        # It's important that this model_name matches what we'd use in _load_model
        # if we were managing the SentenceTransformer instance ourselves for Chroma.
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_name
        )
    except ImportError:
        log.error(
            "chromadb.utils.embedding_functions could not be imported. Ensure chromadb is installed correctly."
        )
        raise
    except Exception as e:
        log.error(
            f"Failed to create SentenceTransformerEmbeddingFunction for model '{model_name}': {e}",
            exc_info=True,
        )
        raise


if __name__ == "__main__":
    # Example Usage (for testing this module directly)
    logging.basicConfig(level=logging.INFO)
    log.info("Testing embedding service...")
    try:
        test_text_1 = "This is a test sentence for the embedding service."
        embedding_1 = get_embedding(test_text_1)
        log.info(
            f"Embedding for '{test_text_1}': {embedding_1[:5]}... (length: {len(embedding_1)})"
        )

        test_text_2 = "Another piece of text to be vectorized."
        embedding_2 = get_embedding(test_text_2)
        log.info(
            f"Embedding for '{test_text_2}': {embedding_2[:5]}... (length: {len(embedding_2)})"
        )

        # Test that model is not reloaded
        log.info("Requesting another embedding to test model caching...")
        embedding_3 = get_embedding("Testing model caching.")
        log.info(
            f"Embedding for 'Testing model caching.': {embedding_3[:5]}... (length: {len(embedding_3)})"
        )

    except RuntimeError as e:
        log.error(f"Test failed: {e}")
    except Exception as e:
        log.error(f"An unexpected error occurred during testing: {e}", exc_info=True)
