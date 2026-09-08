from datetime import UTC, datetime

import pytest

from src.infrastructure.interfaces import IncidentRecord
from src.memory.embedder import IncidentEmbedder
from src.memory.vector_store import IncidentMemoryStore


def test_embedder_deterministic_and_normalized():
    embedder = IncidentEmbedder(dimension=64)
    text1 = "Pod memory limit exceeded OOMKilled"
    text2 = "Pod memory limit exceeded OOMKilled"
    text3 = "Unrelated database timeout"

    vec1 = embedder.embed_text(text1)
    vec2 = embedder.embed_text(text2)
    vec3 = embedder.embed_text(text3)

    assert len(vec1) == 64
    assert vec1 == vec2  # Deterministic
    assert vec1 != vec3

    # Similarity
    sim_identical = embedder.cosine_similarity(vec1, vec2)
    assert pytest.approx(sim_identical, 0.001) == 1.0

    sim_diff = embedder.cosine_similarity(vec1, vec3)
    assert sim_diff < 1.0


@pytest.mark.asyncio
async def test_memory_store_index_and_search(tmp_path, monkeypatch):
    store = IncidentMemoryStore()
    store._storage_path = tmp_path / "test_memory.json"
    store._documents.clear()

    rec1 = IncidentRecord(
        incident_id="inc-oom-1",
        service="checkout-service",
        environment="production",
        severity="high",
        status="resolved",
        created_at=datetime.now(UTC),
        title="OOMKilled pod in checkout",
        probable_cause="Memory limit 512Mi insufficient for peak load",
        confidence=0.9,
        evidence_summary=["Pod terminated with exit code 137"],
    )

    rec2 = IncidentRecord(
        incident_id="inc-redis-2",
        service="auth-service",
        environment="production",
        severity="medium",
        status="resolved",
        created_at=datetime.now(UTC),
        title="Redis connection pool exhaustion",
        probable_cause="Slow client leaked connections",
        confidence=0.88,
        evidence_summary=["Redis max clients reached 10000"],
    )

    await store.index_record(rec1)
    await store.index_record(rec2)

    # Search for memory relevant to OOM
    results = await store.search("checkout pod memory limit exit code 137", top_k=2)
    assert len(results) >= 1
    top_doc, score = results[0]
    assert top_doc.incident_id == "inc-oom-1"
    assert "checkout" in top_doc.service
    assert score > 0.3

    # Test RAG context formatting
    rag_context = await store.get_rag_context("checkout-service", "checkout memory limit crash")
    assert "Historical Incident Memory (RAG)" in rag_context
    assert "inc-oom-1" in rag_context
