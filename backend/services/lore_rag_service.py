"""
Lore RAG Service - PGVector integration for semantic search of user knowledge base.

Features:
- Embed lore entries using nomic-embed-text via Ollama
- Store embeddings in PostgreSQL with PGVector
- Retrieve relevant lore context during generation
- Support similarity search for contextual injection
"""

import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import httpx

from backend.models.schemas import LoreCollection, LoreEntry
from backend.db.session import AsyncSessionLocal

logger = logging.getLogger("kotodama.services.lore_rag")


class LoreRAGService:
    """Service for Lore RAG (Retrieval-Augmented Generation) using PGVector."""

    def __init__(self, ollama_base_url: str = "http://localhost:11434"):
        self.ollama_base_url = ollama_base_url
        self.embedding_model = "nomic-embed-text"
        self.embedding_dimension = 768

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for text using Ollama."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.ollama_base_url}/api/embeddings",
                    json={
                        "model": self.embedding_model,
                        "prompt": text,
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("embedding", [])
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            # Return zero vector as fallback
            return [0.0] * self.embedding_dimension

    async def store_lore_entry(
        self,
        collection_id: int,
        entry_type: str,
        name: str,
        content: str,
        entry_metadata: dict | None = None,
    ) -> LoreEntry:
        """Store a lore entry with its embedding."""
        # Generate embedding
        embedding_text = f"{entry_type}: {name}\n{content}"
        embedding = await self.generate_embedding(embedding_text)

        async with AsyncSessionLocal() as session:
            entry = LoreEntry(
                lore_collection_id=collection_id,
                entry_type=entry_type,
                name=name,
                content=content,
                entry_metadata=entry_metadata or {},
                embedding=embedding,
            )
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            logger.info(f"Stored lore entry: {name} ({entry_type})")
            return entry

    async def retrieve_relevant_lore(
        self,
        collection_id: int,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.7,
    ) -> list[LoreEntry]:
        """Retrieve most relevant lore entries for a query using cosine similarity."""
        # Generate query embedding
        query_embedding = await self.generate_embedding(query)

        async with AsyncSessionLocal() as session:
            # Get all entries for this collection
            result = await session.execute(
                select(LoreEntry)
                .where(LoreEntry.lore_collection_id == collection_id)
                .options(selectinload(LoreEntry.lore_collection))
            )
            entries = result.scalars().all()

            if not entries:
                logger.warning(f"No lore entries found for collection {collection_id}")
                return []

            # Calculate cosine similarity manually (PGVector would do this in SQL)
            scored_entries = []
            for entry in entries:
                if entry.embedding:
                    similarity = self._cosine_similarity(query_embedding, entry.embedding)
                    if similarity >= similarity_threshold:
                        scored_entries.append((similarity, entry))

            # Sort by similarity and return top_k
            scored_entries.sort(key=lambda x: x[0], reverse=True)
            top_entries = [entry for _, entry in scored_entries[:top_k]]

            logger.info(
                f"Retrieved {len(top_entries)} relevant lore entries for collection {collection_id}"
            )
            return top_entries

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if len(vec1) != len(vec2) or not vec1 or not vec2:
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = sum(a * a for a in vec1) ** 0.5
        magnitude2 = sum(b * b for b in vec2) ** 0.5

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)

    async def get_collection_context(
        self, collection_id: int, context_query: str = "game design"
    ) -> str:
        """Get formatted lore context string for injection into agent prompts."""
        entries = await self.retrieve_relevant_lore(collection_id, context_query)

        if not entries:
            return ""

        context_parts = []
        for entry in entries:
            context_parts.append(f"[{entry.entry_type.upper()}] {entry.name}:\n{entry.content}")

        return "\n\n".join(context_parts)

    async def delete_lore_entry(self, entry_id: int) -> bool:
        """Delete a lore entry."""
        async with AsyncSessionLocal() as session:
            entry = await session.get(LoreEntry, entry_id)
            if entry:
                await session.delete(entry)
                await session.commit()
                logger.info(f"Deleted lore entry {entry_id}")
                return True
            return False

    async def get_collection_entries(self, collection_id: int) -> list[LoreEntry]:
        """Get all entries in a collection."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(LoreEntry).where(LoreEntry.lore_collection_id == collection_id)
            )
            return list(result.scalars().all())


# Singleton instance
_lore_rag_service: Optional[LoreRAGService] = None


def get_lore_rag_service() -> LoreRAGService:
    """Get or create LoreRAGService singleton."""
    global _lore_rag_service
    if _lore_rag_service is None:
        _lore_rag_service = LoreRAGService()
    return _lore_rag_service
