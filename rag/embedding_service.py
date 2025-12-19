import logging
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from db import db_session
from rag.models import RAGChunk
from rag.repository import RAGRepository
from services import openai_client

logger = logging.getLogger(__name__)

class EmbeddingService:
    
    EMBEDDING_MODEL = "text-embedding-3-small"
    
    def __init__(self):
        self.engine = db_session.get_engine()
        
    async def ingest_content(
        self,
        collection_name: str,
        external_id: str,
        content: str,
        metadata: Dict[str, Any],
        source: str,
        description: Optional[str] = None
    ) -> UUID:
    
        async with AsyncSession(self.engine) as session:
            repo = RAGRepository(session)
            
            collection_id = await repo.get_or_create_collection(
                name=collection_name,
                description=description or f"Collection for {collection_name}"
            )
            
            # file location link if its a file
            uri = metadata.get("url") or metadata.get("uri") or ""
            
            document_id = await repo.get_or_create_document(
                collection_id=collection_id,
                external_id=external_id,
                uri=uri,
                source=source
            )
            
            next_ord = await repo.get_next_ord(document_id)
            
            embeddings = await openai_client.generate_embeddings([content], model=self.EMBEDDING_MODEL)
            embedding = embeddings[0]
            
            if "created_at" not in metadata:
                metadata["created_at"] = datetime.utcnow().isoformat()
                
            # Insert chunk
            chunk_id = await repo.create_chunk(
                document_id=document_id,
                ord=next_ord,
                content=content,
                metadata=metadata,
                embedding=embedding,
                tokens=len(content.split())
            )
            
            await session.commit()
            
            logger.info(f"Ingested content into collection '{collection_name}' (doc_id={document_id})")
            return chunk_id

    async def search_similar(
        self,
        collection_name: str,
        query_text: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generic retrieval method using vector similarity.
        Returns list of matches with content, metadata, and similarity score.
        """
        # 1. Generate query embedding
        embeddings = await openai_client.generate_embeddings([query_text], model=self.EMBEDDING_MODEL)
        query_embedding = embeddings[0]
        
        async with AsyncSession(self.engine) as session:
            repo = RAGRepository(session)
            
            rows = await repo.search_similar_chunks(
                collection_name=collection_name,
                query_embedding=query_embedding,
                limit=limit,
                filters=filters
            )
            
            matches = []
            for row in rows:
                matches.append({
                    "chunk": RAGChunk(
                        id=row.id,
                        document_id=row.document_id,
                        ord=row.ord,
                        content=row.content,
                        metadata=row.metadata,
                        tokens=row.tokens,
                        created_at=row.created_at
                        # embedding excluded for performance/size
                    ),
                    "score": float(row.similarity_score)
                })
                
            logger.info(f"Found {len(matches)} matches in '{collection_name}' for query")
            return matches
