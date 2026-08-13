"""
API routes for Lore/RAG management.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List

from backend.services.lore_rag_service import get_lore_rag_service
from backend.schemas.api_schemas import (
    LoreCollectionCreate, LoreCollection,
    LoreEntryCreate, LoreEntry,
)

router = APIRouter()


class LoreSearchRequest(BaseModel):
    """Search query for lore collection."""
    query: str
    limit: int = 5


class LoreSearchResult(BaseModel):
    """Search result with similarity score."""
    entry_id: int
    name: str
    content: str
    entry_type: str
    similarity_score: float


@router.post("/collections", response_model=dict)
async def create_collection(collection: LoreCollectionCreate):
    """Create a new lore collection (universe)."""
    # TODO: Implement DB storage
    return {
        "success": True,
        "message": "Lore collection created",
        "collection_id": 1  # Mock ID
    }


@router.get("/collections", response_model=List[LoreCollection])
async def list_collections():
    """List all lore collections for current user."""
    # TODO: Implement DB query
    return []


@router.get("/collections/{collection_id}", response_model=LoreCollection)
async def get_collection(collection_id: int):
    """Get a specific lore collection with entries."""
    # TODO: Implement DB query
    raise HTTPException(status_code=404, detail="Collection not found")


@router.delete("/collections/{collection_id}")
async def delete_collection(collection_id: int):
    """Delete a lore collection and all its entries."""
    # TODO: Implement deletion
    return {"success": True, "message": f"Collection {collection_id} deleted"}


@router.post("/collections/{collection_id}/entries", response_model=LoreEntry)
async def add_entry(collection_id: int, entry: LoreEntryCreate):
    """Add a new lore entry to a collection."""
    # TODO: Implement DB storage + vectorization
    return LoreEntry(
        id=1,
        lore_collection_id=collection_id,
        entry_type=entry.entry_type,
        name=entry.name,
        content=entry.content,
        metadata=entry.metadata,
        created_at=None  # type: ignore
    )


@router.get("/collections/{collection_id}/entries", response_model=List[LoreEntry])
async def list_entries(collection_id: int):
    """List all entries in a collection."""
    # TODO: Implement DB query
    return []


@router.delete("/collections/{collection_id}/entries/{entry_id}")
async def delete_entry(collection_id: int, entry_id: int):
    """Delete a lore entry."""
    # TODO: Implement deletion
    return {"success": True, "message": f"Entry {entry_id} deleted"}


@router.post("/collections/{collection_id}/search", response_model=List[LoreSearchResult])
async def search_collection(collection_id: int, request: LoreSearchRequest):
    """
    Search within a lore collection using semantic similarity.
    
    Uses PGVector to find entries most similar to the query.
    """
    lore_service = get_lore_rag_service()
    
    try:
        # Get context from RAG service
        context = await lore_service.get_collection_context(
            collection_id=collection_id,
            query=request.query,
            limit=request.limit
        )
        
        # Convert to search results
        return [
            LoreSearchResult(
                entry_id=i,
                name=f"Entry {i}",
                content=context,
                entry_type="character",
                similarity_score=0.95
            )
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/vectorize/{collection_id}")
async def vectorize_collection(collection_id: int):
    """
    Trigger vectorization of all entries in a collection.
    
    This is called when a collection is updated or after bulk import.
    """
    lore_service = get_lore_rag_service()
    
    # TODO: Implement async vectorization job
    return {
        "success": True,
        "message": f"Vectorization started for collection {collection_id}",
        "status": "processing"
    }
