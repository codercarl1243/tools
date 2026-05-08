"""Tests for kb/query.py tag filtering."""

from unittest.mock import patch, MagicMock
import numpy as np
import chromadb.errors


def test_query_not_found_raises_correct_exception():
    """verify NotFoundError is caught and friendly message printed."""
    from query import query_project

    mock_client = MagicMock()
    mock_client.get_collection.side_effect = chromadb.errors.NotFoundError("not found")

    with patch("query._get_client", return_value=mock_client), \
         patch("query.get_model", return_value=MagicMock()), \
         patch("builtins.print") as mock_print:
        result = query_project("nonexistent", "test query")
        assert result == []
        mock_print.assert_called_once()
        assert "No index found" in mock_print.call_args[0][0]


def _common_fixtures():
    """Shared mocks for query tests."""
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "documents": [["text"]],
        "metadatas": [[{"path": "a.rs", "chunk": 0}]],
        "distances": [[0.5]],
    }
    mock_client = MagicMock()
    mock_client.get_collection.return_value = mock_collection
    return mock_client, mock_collection


def _mock_model():
    """Mock model that mimics sentence-transformers encode return value."""
    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([[0.1] * 384])
    return mock_model


def test_query_tag_filter_passed_to_chromadb():
    """When tag is provided, ChromaDB where filter should be set."""
    from query import query_project

    mock_client, mock_collection = _common_fixtures()

    with patch("query._get_client", return_value=mock_client), \
         patch("query.get_model", return_value=_mock_model()), \
         patch("builtins.print"):
        query_project("proj", "test", tag="v1")

    call_kwargs = mock_collection.query.call_args[1]
    assert call_kwargs["where"] == {"tag": "v1"}


def test_query_no_tag_no_filter():
    """When tag is not provided, where filter should be None."""
    from query import query_project

    mock_client, mock_collection = _common_fixtures()

    with patch("query._get_client", return_value=mock_client), \
         patch("query.get_model", return_value=_mock_model()), \
         patch("builtins.print"):
        query_project("proj", "test")

    call_kwargs = mock_collection.query.call_args[1]
    assert call_kwargs["where"] is None
