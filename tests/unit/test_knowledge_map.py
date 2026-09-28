"""Knowledge map edges: similar documents connect, unrelated ones don't, top-k caps the degree."""
from services.rag.knowledge_map import centroid, document_edges


def test_centroid_is_unit_and_length_independent():
    c1 = centroid([[1, 0], [1, 0]])
    c2 = centroid([[10, 0]])
    assert c1 == c2 == [1.0, 0.0]


def test_edges_connect_similar_and_skip_unrelated():
    vecs = {"a": [[1, 0, 0]], "b": [[0.9, 0.1, 0]], "c": [[0, 0, 1]]}
    edges = document_edges(vecs, k=3, min_sim=0.55)
    assert [(e["source"], e["target"]) for e in edges] == [("a", "b")]
    assert 0.9 < edges[0]["similarity"] <= 1


def test_top_k_limits_neighbours_but_keeps_edges_undirected():
    vecs = {"hub": [[1, 0]], "x": [[0.99, 0.1]], "y": [[0.98, 0.2]], "z": [[0.97, 0.25]]}
    edges = document_edges(vecs, k=1, min_sim=0.5)
    pairs = {(e["source"], e["target"]) for e in edges}
    assert all(a < b for a, b in pairs)  # one direction only, no duplicates
    assert ("hub", "x") in pairs


def test_documents_without_vectors_are_ignored():
    assert document_edges({"a": [[1, 0]], "empty": []}) == []
