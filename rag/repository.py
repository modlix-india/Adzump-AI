import logging
import hashlib
import json
from typing import List, Dict, Any, Optional, Sequence
from uuid import UUID
from sqlalchemy import text, Row
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class RAGRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_collection(self, name: str, description: str) -> UUID:
        """Get or create collection by name"""
        result = await self.session.execute(
            text("SELECT id FROM rag_collections WHERE name = :name"), {"name": name}
        )
        row = result.fetchone()

        if row:
            return row.id

        result = await self.session.execute(
            text("""
                INSERT INTO rag_collections (name, description)
                VALUES (:name, :description)
                RETURNING id
            """),
            {"name": name, "description": description},
        )
        row = result.fetchone()
        if not row:
            raise SQLAlchemyError(f"Failed to create collection '{name}'")
        return row.id

    async def get_or_create_document(
        self, collection_id: UUID, external_id: str, uri: str, source: str
    ) -> UUID:
        # First, try to fetch the document
        result = await self.session.execute(
            text("""
                SELECT id FROM rag_documents
                WHERE collection_id = :collection_id AND external_id = :external_id
            """),
            {"collection_id": collection_id, "external_id": external_id},
        )
        row = result.fetchone()
        if row:
            return row.id

        # If not exists, insert new document
        sha256 = hashlib.sha256(f"{external_id}{uri}".encode()).hexdigest()
        result = await self.session.execute(
            text("""
                INSERT INTO rag_documents 
                (collection_id, external_id, uri, source, sha256)
                VALUES (:collection_id, :external_id, :uri, :source, :sha256)
                RETURNING id
            """),
            {
                "collection_id": collection_id,
                "external_id": external_id,
                "uri": uri,
                "source": source,
                "sha256": sha256,
            },
        )
        row = result.fetchone()
        if not row:
            raise SQLAlchemyError(f"Failed to create document '{external_id}'")
        return row.id

    async def get_next_ord(self, document_id: UUID) -> int:
        """Get next ordinal number for chunks in a document"""
        ord_result = await self.session.execute(
            text(
                "SELECT COALESCE(MAX(ord), -1) + 1 as next_ord FROM rag_chunks WHERE document_id = :doc_id"
            ),
            {"doc_id": document_id},
        )
        row = ord_result.fetchone()
        if not row:
            return 0  # Fallback (though this query should always return a row)
        return row.next_ord

    async def create_chunk(
        self,
        document_id: UUID,
        ord: int,
        content: str,
        metadata: Dict[str, Any],
        embedding: List[float],
        tokens: int,
    ) -> UUID:
        """Create a new chunk with embedding"""
        # Convert embedding list to PostgreSQL array format
        # Why? asyncpg with SQLAlchemy text() doesn't auto-convert Python lists to PostgreSQL arrays
        # We must manually format it as a string that PostgreSQL can parse as an array
        
        logger.info(f"🔍 EMBEDDING CONVERSION DEBUG:")
        logger.info(f"  Input type: {type(embedding)}")
        logger.info(f"  Input length: {len(embedding)}")
        logger.info(f"  First 5 values: {embedding[:5]}")
        
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        
        logger.info(f"  Converted string (first 100 chars): {embedding_str[:100]}...")
        logger.info(f"  Converted string (last 50 chars): ...{embedding_str[-50:]}")
        logger.info(f"  Reason: asyncpg needs string format '[x,y,z]' for vector type cast")
        
        result = await self.session.execute(
            text("""
                INSERT INTO rag_chunks 
                (document_id, ord, content, metadata, tokens, embedding)
                VALUES (:document_id, :ord, :content, :metadata, :tokens, CAST(:embedding_vec AS vector))
                RETURNING id
            """),
            {
                "document_id": document_id,
                "ord": ord,
                "content": content,
                "metadata": json.dumps(metadata),
                "tokens": tokens,
                "embedding_vec": embedding_str,
            },
        )
        row = result.fetchone()
        if not row:
            raise SQLAlchemyError(f"Failed to create chunk for document '{document_id}'")
        return row.id

    async def search_similar_chunks(
        self,
        collection_name: str,
        query_embedding: List[float],
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Sequence[Row]:
        """
        Search for similar chunks in a collection.
        Returns rows with keys: id, document_id, ord, content, metadata, tokens, created_at, similarity_score
        """
        # Convert embedding list to PostgreSQL array format for similarity search
        logger.info(f"🔍 SEARCH EMBEDDING CONVERSION:")
        logger.info(f"  Query embedding length: {len(query_embedding)}")
        
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        
        logger.info(f"  Converted for vector similarity: {embedding_str[:80]}...")
        
        query_sql = """
            SELECT 
                c.id,
                c.document_id,
                c.ord,
                c.content,
                c.metadata,
                c.tokens,
                c.created_at,
                1 - (c.embedding <=> CAST(:embedding_vec AS vector)) as similarity_score
            FROM rag_chunks c
            JOIN rag_documents d ON c.document_id = d.id
            JOIN rag_collections col ON d.collection_id = col.id
            WHERE col.name = :collection_name
        """

        params = {
            "collection_name": collection_name,
            "embedding_vec": embedding_str,
            "limit": limit,
        }

        # Apply metadata filters
        if filters:
            for key, value in filters.items():
                # Basic sanitization for keys to prevent SQL injection via key name
                # Ideally keys should be validated against a schema
                safe_key = key.replace("'", "")
                query_sql += f" AND c.metadata->>'{safe_key}' = :filter_{safe_key}"
                params[f"filter_{safe_key}"] = str(value)

        query_sql += " ORDER BY similarity_score DESC LIMIT :limit"

        result = await self.session.execute(text(query_sql), params)
        return result.fetchall()
