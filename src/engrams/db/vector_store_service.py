# src/engrams/db/vector_store_service.py
import logging
import os
import shutil  # For deleting workspace vector store
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from ..core import embedding_service  # Use our embedding service

log = logging.getLogger(__name__)

# Global cache for ChromaDB clients per workspace_id to avoid reinitialization
_chroma_clients: Dict[str, chromadb.PersistentClient] = {}
_chroma_collections: Dict[str, Dict[str, chromadb.Collection]] = (
    {}
)  # workspace_id -> {collection_name: Collection}

DEFAULT_COLLECTION_NAME = "engrams_semantic_store"


def _get_vector_store_path(workspace_id: str) -> str:
    """Determines the path for the vector store for a given workspace."""
    # IMPORTANT: Ensure workspace_id is a safe path component.
    # This path should be inside the .engrams directory for the workspace.
    # Example: /path/to/workspace/.engrams/vector_store
    # For now, using a simpler structure, assuming workspace_id is the root.
    # This needs to align with how SQLite DB path is handled.
    # From Design Doc: context_portal/[workspace_id]/vector_store/
    # This implies workspace_id is a name, not a full path.
    # Let's assume a base data directory for engrams, then workspace_id subdir.
    # For now, let's assume workspace_id IS the base path for that workspace's data.

    # This path logic needs to be robust and align with overall project structure.
    # For this example, let's assume workspace_id is a directory path.
    # A more robust solution would use a central config for data paths.
    if not os.path.isdir(workspace_id):
        log.warning(
            f"Workspace path '{workspace_id}' does not exist or is not a directory. Vector store path may be invalid."
        )
        # Or raise error, depending on how workspace_id is managed.

    # Path as per design doc: context_portal/[workspace_id]/vector_store/
    # This implies a structure where 'engrams' is a subdir in the actual project,
    # and then a specific workspace_id folder under that.
    # Let's assume workspace_id is the root of the project for now for simplicity of this module.
    # The actual path construction should be centralized.
    # For now: workspace_root/.engrams_db/vector_store
    # This is a deviation from design doc to make it runnable standalone, needs to be fixed.
    # Design Doc: context_portal/[workspace_id]/vector_store/
    # Let's stick to the design doc as much as possible.
    # If workspace_id = "/abs/path/to/project", then this would be:
    # "/abs/path/to/project/context_portal/vector_store" (if workspace_id is the name of the folder inside context_portal)
    # OR if workspace_id is the full project path:
    # "/abs/path/to/project/.engrams_data/vector_store" (more typical)

    # Path for ChromaDB persistence.
    # It will be located at: [workspace_id]/context_portal/engrams_vector_data/
    # This aligns with the SQLite DB being in [workspace_id]/context_portal/context.db
    # workspace_id is assumed to be the root path of the user's project.

    # Ensure the 'engrams' directory exists at the workspace root first.
    # The SQLite setup in config.py also creates this, but good to be robust.
    context_portal_base_dir = os.path.join(workspace_id, "engrams")
    os.makedirs(context_portal_base_dir, exist_ok=True)

    vector_db_path = os.path.join(
        context_portal_base_dir, "engrams_vector_data"
    )  # No leading dot, and inside context_portal
    os.makedirs(vector_db_path, exist_ok=True)
    log.info(f"Vector store path set to: {vector_db_path}")
    return vector_db_path


def get_chroma_client(workspace_id: str) -> chromadb.PersistentClient:
    """
    Gets or initializes a persistent ChromaDB client for the given workspace_id.
    Clients are cached globally.
    """
    if workspace_id not in _chroma_clients:
        vector_store_path = _get_vector_store_path(workspace_id)
        log.info(
            f"Initializing ChromaDB client for workspace '{workspace_id}' at path: {vector_store_path}"
        )
        try:
            # Settings for on-disk persistence.
            # allow_reset=True can be useful during development if schema changes.
            client = chromadb.PersistentClient(
                path=vector_store_path,
                settings=ChromaSettings(allow_reset=True, anonymized_telemetry=False),
            )
            _chroma_clients[workspace_id] = client
        except Exception as e:
            log.error(
                f"Failed to initialize ChromaDB client for workspace '{workspace_id}': {e}",
                exc_info=True,
            )
            raise
    return _chroma_clients[workspace_id]


def get_or_create_collection(
    workspace_id: str, collection_name: str = DEFAULT_COLLECTION_NAME
) -> chromadb.Collection:
    """
    Gets or creates a ChromaDB collection for the given workspace_id and collection_name.
    Collections are cached globally.
    """
    if workspace_id not in _chroma_collections:
        _chroma_collections[workspace_id] = {}

    if collection_name not in _chroma_collections[workspace_id]:
        client = get_chroma_client(workspace_id)
        log.info(
            f"Getting or creating ChromaDB collection '{collection_name}' for workspace '{workspace_id}'."
        )
        try:
            # Get the embedding function from our service to ensure consistency
            chroma_ef = embedding_service.get_chroma_embedding_function()

            # When providing pre-calculated embeddings (as we do in upsert_item_embedding),
            # ChromaDB does not strictly need an embedding_function at the collection level
            # for the upsert operation itself if you provide embeddings directly.
            # However, if you ever wanted to use collection.add(documents=["text"])
            # and have Chroma calculate embeddings, or if Chroma's internal query mechanisms
            # might re-embed or compare based on text, setting it is safer for consistency.
            # Also, get_or_create_collection requires it if the collection *might* be created
            # and needs to know how to handle future text additions.
            collection = client.get_or_create_collection(
                name=collection_name, embedding_function=chroma_ef
            )
            _chroma_collections[workspace_id][collection_name] = collection
        except Exception as e:
            log.error(
                f"Failed to get or create ChromaDB collection '{collection_name}' for workspace '{workspace_id}': {e}",
                exc_info=True,
            )
            raise

    return _chroma_collections[workspace_id][collection_name]


def upsert_item_embedding(
    workspace_id: str,
    item_type: str,
    item_id: str,  # This is the original Engrams item's ID (e.g., decision_id, custom_data primary key)
    vector: List[float],
    metadata: Dict[
        str, Any
    ],  # Should include original_field, category, tags, timestamps etc.
    collection_name: str = DEFAULT_COLLECTION_NAME,
):
    """
    Adds or updates an embedding in ChromaDB.
    The document ID in ChromaDB will be f"{item_type}_{item_id}".
    If the item has multiple embeddable fields, this assumes one primary vector per item,
    or that the caller manages separate calls for separate field embeddings with distinct doc_ids.
    Design doc: "ChromaDB documents will use an ID like itemType_itemId" - implies one vector per item.
    """
    collection = get_or_create_collection(workspace_id, collection_name)
    doc_id = f"{item_type}_{item_id}"

    # Ensure metadata is suitable for ChromaDB (str, int, float, bool, or None)
    # Convert any list values to strings.
    final_metadata = {}
    for key, value in metadata.items():
        if isinstance(value, list):
            final_metadata[key] = ", ".join(map(str, value))
        else:
            final_metadata[key] = value

    # Add item_type and item_id to metadata if not already present, for easier filtering.
    final_metadata["engrams_item_type"] = item_type
    final_metadata["engrams_item_id"] = str(item_id)

    log.debug(
        f"Upserting embedding for doc_id '{doc_id}' in collection '{collection_name}' for workspace '{workspace_id}'."
    )
    try:
        collection.upsert(ids=[doc_id], embeddings=[vector], metadatas=[final_metadata])
        log.info(f"Successfully upserted embedding for doc_id '{doc_id}'.")
    except Exception as e:
        log.error(
            f"Failed to upsert embedding for doc_id '{doc_id}': {e}", exc_info=True
        )
        # Decide on error handling: raise, or return status
        raise


def query_vector_store(
    workspace_id: str,
    query_vector: List[float],
    top_k: int = 5,
    filters: Optional[Dict[str, Any]] = None,  # ChromaDB 'where' clause
    collection_name: str = DEFAULT_COLLECTION_NAME,
) -> List[Dict[str, Any]]:
    """
    Queries the ChromaDB collection for similar embeddings.
    """
    collection = get_or_create_collection(workspace_id, collection_name)
    log.debug(
        f"Querying collection '{collection_name}' in workspace '{workspace_id}' with top_k={top_k}, filters={filters}."
    )
    try:
        results = collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=filters if filters else None,  # Pass None if no filters
            include=[
                "metadatas",
                "distances",
                "documents",
            ],  # 'documents' if text was stored, 'embeddings' if needed
        )
        # Process results:
        # results is a QueryResult object. Example:
        # QueryResult(ids=[['id1', 'id2']], embeddings=None, documents=[['doc1', 'doc2']], metadatas=[[{'key': 'val1'}, {'key': 'val2'}]], distances=[[0.1, 0.2]])
        # We are interested in metadatas and distances primarily to identify original items.

        processed_results = []
        if results and results.get("ids") and results.get("ids")[0]:
            for i, doc_id in enumerate(results["ids"][0]):
                entry = {
                    "chroma_doc_id": doc_id,
                    "distance": (
                        results["distances"][0][i]
                        if results.get("distances") and results["distances"][0]
                        else None
                    ),
                    "metadata": (
                        results["metadatas"][0][i]
                        if results.get("metadatas") and results["metadatas"][0]
                        else None
                    ),
                    # "document_text": results['documents'][0][i] if results.get('documents') and results['documents'][0] else None, # If text was stored
                }
                processed_results.append(entry)

        log.info(f"Vector store query returned {len(processed_results)} results.")
        return processed_results
    except Exception as e:
        log.error(f"Failed to query vector store: {e}", exc_info=True)
        raise


def delete_item_embedding(
    workspace_id: str,
    item_type: str,
    item_id: str,
    collection_name: str = DEFAULT_COLLECTION_NAME,
):
    """
    Deletes an embedding from ChromaDB based on its Engrams item_type and item_id.
    """
    collection = get_or_create_collection(workspace_id, collection_name)
    doc_id = f"{item_type}_{item_id}"
    log.debug(
        f"Attempting to delete embedding for doc_id '{doc_id}' from collection '{collection_name}' for workspace '{workspace_id}'."
    )
    try:
        collection.delete(ids=[doc_id])
        log.info(
            f"Successfully deleted embedding for doc_id '{doc_id}' (if it existed)."
        )
    except Exception as e:
        # ChromaDB might not error if ID doesn't exist, check its behavior.
        # For now, log error and re-raise.
        log.error(
            f"Failed to delete embedding for doc_id '{doc_id}': {e}", exc_info=True
        )
        raise


def delete_workspace_vector_store(workspace_id: str):
    """
    Deletes the entire vector store directory for a given workspace.
    USE WITH CAUTION.
    """
    vector_store_path = _get_vector_store_path(workspace_id)
    if os.path.exists(vector_store_path):
        log.warning(
            f"Deleting entire vector store for workspace '{workspace_id}' at path: {vector_store_path}"
        )
        try:
            # Clear caches if client/collections were loaded
            if workspace_id in _chroma_clients:
                del _chroma_clients[workspace_id]
            if workspace_id in _chroma_collections:
                del _chroma_collections[workspace_id]

            shutil.rmtree(vector_store_path)
            log.info(
                f"Successfully deleted vector store for workspace '{workspace_id}'."
            )
        except Exception as e:
            log.error(
                f"Failed to delete vector store for workspace '{workspace_id}': {e}",
                exc_info=True,
            )
            raise
    else:
        log.info(
            f"No vector store found at '{vector_store_path}' for workspace '{workspace_id}', nothing to delete."
        )


if __name__ == "__main__":
    # Example Usage (for testing this module directly)
    logging.basicConfig(level=logging.DEBUG)  # Use DEBUG for more verbose output

    # This test needs the embedding_service.py to be importable
    # For simplicity, let's assume it is or mock its output.
    # Mocking get_embedding:
    def get_mock_embedding(text: str) -> List[float]:
        # Return a fixed-size vector, e.g., 384 for all-MiniLM-L6-v2
        # Simple hash-based mock, not a real embedding
        import hashlib

        val = int(hashlib.md5(text.encode()).hexdigest(), 16)
        return [(val + i * 0.01) / (10**10) for i in range(384)]

    # Test workspace - use a temporary directory for testing
    import tempfile

    test_workspace_dir = tempfile.mkdtemp(prefix="engrams_test_ws_")
    log.info(f"Using temporary test workspace: {test_workspace_dir}")

    try:
        log.info("--- Testing ChromaDB Service ---")

        # Test get_or_create_collection
        collection = get_or_create_collection(test_workspace_dir, "my_test_collection")
        log.info(
            f"Got/Created collection: {collection.name}, count: {collection.count()}"
        )
        assert collection.name == "my_test_collection"

        # Test upsert
        mock_vector_1 = get_mock_embedding("This is decision 1 about databases.")
        metadata_1 = {
            "original_field": "summary",
            "tags": ["db", "performance"],
            "timestamp_created": "2023-01-01T10:00:00Z",
        }
        upsert_item_embedding(
            test_workspace_dir,
            "decision",
            "1",
            mock_vector_1,
            metadata_1,
            collection_name="my_test_collection",
        )

        mock_vector_2 = get_mock_embedding("This is custom data about API keys.")
        metadata_2 = {
            "category": "secrets",
            "timestamp_created": "2023-01-02T11:00:00Z",
        }
        upsert_item_embedding(
            test_workspace_dir,
            "custom_data",
            "api_key_service_x",
            mock_vector_2,
            metadata_2,
            collection_name="my_test_collection",
        )

        log.info(f"Collection count after upserts: {collection.count()}")
        assert collection.count() == 2

        # Test query
        query_text = "information about databases"
        query_vector = get_mock_embedding(query_text)

        log.info(f"Querying for: '{query_text}'")
        results = query_vector_store(
            test_workspace_dir,
            query_vector,
            top_k=1,
            collection_name="my_test_collection",
        )
        log.info(f"Query results: {results}")
        assert len(results) == 1
        assert results[0]["chroma_doc_id"] == "decision_1"
        assert results[0]["metadata"]["engrams_item_type"] == "decision"

        # Test query with filter
        log.info(f"Querying for: '{query_text}' with item_type filter 'custom_data'")
        # ChromaDB filter syntax: {"metadata_field": "value"} or {"$operator": {"metadata_field": "value"}}
        # Our metadata keys are engrams_item_type, engrams_item_id, etc.
        results_filtered = query_vector_store(
            test_workspace_dir,
            query_vector,
            top_k=1,
            filters={"engrams_item_type": "custom_data"},
            collection_name="my_test_collection",
        )
        log.info(f"Filtered query results: {results_filtered}")
        # This query might still return decision_1 if it's closer, filter applies to candidates.
        # If "information about databases" is much closer to decision_1 than "API keys", it might still be top.
        # A better test for filtering would be a query text closer to the filtered item.
        query_text_secrets = "confidential api key"
        query_vector_secrets = get_mock_embedding(query_text_secrets)
        results_filtered_secrets = query_vector_store(
            test_workspace_dir,
            query_vector_secrets,
            top_k=1,
            filters={"engrams_item_type": "custom_data"},
            collection_name="my_test_collection",
        )
        log.info(
            f"Querying for '{query_text_secrets}' with item_type filter 'custom_data': {results_filtered_secrets}"
        )
        assert len(results_filtered_secrets) == 1
        assert (
            results_filtered_secrets[0]["chroma_doc_id"]
            == "custom_data_api_key_service_x"
        )

        # Test delete
        delete_item_embedding(
            test_workspace_dir, "decision", "1", collection_name="my_test_collection"
        )
        log.info(f"Collection count after delete: {collection.count()}")
        assert collection.count() == 1

        # Verify deletion
        results_after_delete = query_vector_store(
            test_workspace_dir,
            query_vector,
            top_k=1,
            collection_name="my_test_collection",
        )
        log.info(f"Query results after delete: {results_after_delete}")
        if results_after_delete:  # if something is returned
            assert results_after_delete[0]["chroma_doc_id"] != "decision_1"

        log.info("--- ChromaDB Service Test Completed Successfully ---")

    except Exception as e:
        log.error(
            f"An error occurred during vector_store_service testing: {e}", exc_info=True
        )
    finally:
        # Clean up the temporary directory
        log.info(f"Cleaning up temporary test workspace: {test_workspace_dir}")
        # First, try to delete the vector store explicitly to test that function
        try:
            delete_workspace_vector_store(
                test_workspace_dir
            )  # This should clear _chroma_clients and _chroma_collections cache for this ws_id
        except Exception as e:
            log.error(f"Error during explicit vector store deletion: {e}")

        # Then remove the whole temp dir
        try:
            shutil.rmtree(test_workspace_dir)
        except Exception as e:
            log.error(f"Error cleaning up temp directory {test_workspace_dir}: {e}")
