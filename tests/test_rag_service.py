import os
import sys
import unittest
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STREAMLIT_APP_ROOT = os.path.join(PROJECT_ROOT, "streamlit_app")
for path in (PROJECT_ROOT, STREAMLIT_APP_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import rag_service


class RagServiceTests(unittest.TestCase):
    def _inject_state(self, chunks, embeddings):
        """Inject fake chunk/embedding state directly into the module."""
        rag_service._chunks = chunks
        rag_service._embeddings = embeddings
        rag_service._initialized = True

    def _make_embed_mock(self, vector):
        """Return a mock that mimics client.models.embed_content response."""
        mock_response = MagicMock()
        mock_emb = MagicMock()
        mock_emb.values = vector
        mock_response.embeddings = [mock_emb]
        return mock_response

    def test_retrieve_ranked_by_score_descending(self):
        """retrieve() results must be ordered by cosine similarity score descending."""
        # Three chunks with orthogonal unit vectors
        chunks = [
            {"text": "City: New York, Region: Northeast", "source": "map_cities.json"},
            {"text": "Vehicle type: UberX, base rate: $2.50", "source": "map_vehicle_types.json"},
            {"text": "Cancellation reason: Driver cancelled", "source": "map_cancellation_reasons.json"},
        ]
        embeddings = [
            [1.0, 0.0, 0.0],   # most similar to query
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
        self._inject_state(chunks, embeddings)

        # Query embedding points toward chunk[0]
        query_vector = [0.95, 0.3, 0.1]
        mock_response = self._make_embed_mock(query_vector)

        with patch.object(rag_service, "_embed_single", return_value=query_vector):
            results = rag_service.retrieve("New York city market", top_k=3)

        self.assertEqual(len(results), 3)
        scores = [r["score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True), "Results must be sorted by score descending")
        # Top result should be the New York chunk (most aligned)
        self.assertIn("New York", results[0]["text"])

    def test_no_pii_in_chunks(self):
        """passenger_name and driver_name must not appear in any chunk text."""
        # Reset so _build_chunks() runs from the actual source files
        rag_service._initialized = False
        rag_service._chunks = []
        rag_service._embeddings = []

        # Run only chunk building without embedding
        chunks = rag_service._build_chunks()

        pii_fields = ("passenger_name", "driver_name")
        for chunk in chunks:
            text = chunk.get("text", "").lower()
            for field in pii_fields:
                self.assertNotIn(
                    field,
                    text,
                    f"PII field '{field}' found in chunk from {chunk.get('source')}: {chunk['text'][:80]}",
                )

    def tearDown(self):
        # Reset module state so tests don't bleed into each other
        rag_service._initialized = False
        rag_service._chunks = []
        rag_service._embeddings = []


if __name__ == "__main__":
    unittest.main()
