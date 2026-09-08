"""Vector memory store for indexing and retrieving historical incidents (RAG)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from config.settings import PROJECT_ROOT, Settings, get_settings
from src.infrastructure.interfaces import IncidentRecord
from src.memory.embedder import IncidentEmbedder

logger = logging.getLogger("opsmind.memory.vector_store")


@dataclass
class IncidentMemoryDocument:
    """Indexed historical incident memory document."""

    doc_id: str
    incident_id: str
    service: str
    environment: str
    title: str
    probable_cause: str
    summary: str
    recommended_actions: list[str] = field(default_factory=list)
    vector: list[float] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


class IncidentMemoryStore:
    """In-memory and file-backed vector store for incident retrieval."""

    def __init__(
        self,
        settings: Settings | None = None,
        embedder: IncidentEmbedder | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.embedder = embedder or IncidentEmbedder()
        self._documents: dict[str, IncidentMemoryDocument] = {}
        self._storage_path = (PROJECT_ROOT / "data" / "incident_memory.json").resolve()
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Load persisted index from JSON file if it exists."""
        if not self._storage_path.exists():
            return
        try:
            raw_text = self._storage_path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
            for item in data:
                doc = IncidentMemoryDocument(**item)
                self._documents[doc.doc_id] = doc
            logger.info(
                "Loaded %d incident memories from %s", len(self._documents), self._storage_path
            )
        except Exception as exc:
            logger.warning("Could not load vector store from %s: %s", self._storage_path, exc)

    def _persist_to_disk(self) -> None:
        """Persist in-memory documents to disk."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = [asdict(doc) for doc in self._documents.values()]
            self._storage_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not save vector store to disk: %s", exc)

    async def index_incident(
        self,
        incident_id: str,
        service: str,
        environment: str,
        title: str,
        probable_cause: str,
        summary: str,
        recommended_actions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IncidentMemoryDocument:
        """Index a resolved or analyzed incident into the vector store."""
        actions = recommended_actions or []
        combined_text = (
            f"Service: {service}. Title: {title}. Cause: {probable_cause}. "
            f"Summary: {summary}. Actions: {' '.join(actions)}"
        )
        vec = self.embedder.embed_text(combined_text)

        doc = IncidentMemoryDocument(
            doc_id=f"mem-{incident_id}",
            incident_id=incident_id,
            service=service,
            environment=environment,
            title=title,
            probable_cause=probable_cause,
            summary=summary,
            recommended_actions=actions,
            vector=vec,
            created_at=datetime.now(UTC).isoformat(),
            metadata=metadata or {},
        )

        self._documents[doc.doc_id] = doc
        self._persist_to_disk()
        logger.info("Indexed incident memory %s for service %s", incident_id, service)
        return doc

    async def index_record(self, record: IncidentRecord) -> IncidentMemoryDocument:
        """Helper to index directly from an IncidentRecord."""
        return await self.index_incident(
            incident_id=record.incident_id,
            service=record.service,
            environment=record.environment,
            title=record.title,
            probable_cause=record.probable_cause,
            summary=record.evidence_summary[0] if record.evidence_summary else record.title,
            recommended_actions=[],
            metadata={"severity": record.severity, "status": record.status},
        )

    async def search(
        self,
        query_text: str,
        service: str | None = None,
        top_k: int = 3,
        min_similarity: float = 0.05,
    ) -> list[tuple[IncidentMemoryDocument, float]]:
        """Find the top-K most similar historical incidents."""
        if not self._documents:
            return []

        query_vec = self.embedder.embed_text(query_text)
        scored: list[tuple[IncidentMemoryDocument, float]] = []

        for doc in self._documents.values():
            if service and doc.service.lower() != service.lower():
                # Cross-service penalty or skip unless broad search
                pass
            score = self.embedder.cosine_similarity(query_vec, doc.vector)
            if score >= min_similarity:
                scored.append((doc, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    async def get_rag_context(
        self,
        service: str,
        query_text: str,
        top_k: int = 2,
    ) -> str:
        """Format top relevant historical memories for injection into the LLM prompt."""
        matches = await self.search(query_text=query_text, service=service, top_k=top_k)
        if not matches:
            return ""

        context_lines = ["--- Historical Incident Memory (RAG) ---"]
        for idx, (doc, score) in enumerate(matches, start=1):
            actions_str = ", ".join(doc.recommended_actions) if doc.recommended_actions else "N/A"
            header = f"[Past Incident #{idx}] ({doc.incident_id}, {doc.service}, Sim: {score:.2f})"
            context_lines.append(
                f"{header}\n"
                f"  Title: {doc.title}\n"
                f"  Probable Cause: {doc.probable_cause}\n"
                f"  Summary: {doc.summary}\n"
                f"  Resolution Actions: {actions_str}"
            )
        context_lines.append("----------------------------------------")
        return "\n".join(context_lines)


_memory_store_instance: IncidentMemoryStore | None = None


def get_memory_store(settings: Settings | None = None) -> IncidentMemoryStore:
    """Retrieve or create the singleton IncidentMemoryStore instance."""
    global _memory_store_instance
    if _memory_store_instance is None:
        _memory_store_instance = IncidentMemoryStore(settings=settings)
    return _memory_store_instance
