import os
import uuid
import tiktoken
from collections import Counter, defaultdict
from typing import List, Dict, Any, Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, SparseVectorParams, SparseIndexParams, Modifier,
    PointStruct, Filter, FieldCondition, MatchValue, SparseVector, Prefetch,
    FusionQuery, Fusion
)
from config import settings, logger

def get_qdrant_url() -> str:
    """Resolve Qdrant endpoint url dynamically based on environment."""
    url = settings.QDRANT_URL
    is_docker = os.getenv("RUNNING_IN_DOCKER") == "true" or os.path.exists("/.dockerenv")
    if not is_docker and "qdrant:6333" in url:
        return url.replace("qdrant:6333", "127.0.0.1:6333")
    return url

async def init_qdrant_collections():
    """Verify and initialize the 'items' collection in Qdrant with dense and sparse configs."""
    url = get_qdrant_url()
    client = AsyncQdrantClient(url=url)
    try:
        collections = await client.get_collections()
        exists = any(c.name == "items" for c in collections.collections)
        recreate = False
        
        if exists:
            try:
                info = await client.get_collection("items")
                vectors = info.config.params.vectors
                # If the collection doesn't have named vectors config or lacks sparse vectors, recreate it
                if not isinstance(vectors, dict) or "dense" not in vectors:
                    recreate = True
                elif not info.config.params.sparse_vectors:
                    recreate = True
            except Exception as e:
                logger.warning(f"Error checking existing collection config: {e}. Recreating...")
                recreate = True
                
        if recreate:
            logger.info("Recreating Qdrant collection 'items' to support hybrid search")
            await client.delete_collection("items")
            exists = False
            
        if not exists:
            logger.info("Initializing 'items' collection in Qdrant with dense and sparse vectors")
            await client.create_collection(
                collection_name="items",
                vectors_config={
                    "dense": VectorParams(size=1024, distance=Distance.COSINE)
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams(
                        modifier=Modifier.IDF
                    )
                }
            )
    except Exception as e:
        logger.error(f"Failed to initialize Qdrant collections: {e}")
    finally:
        await client.close()

def get_sparse_vector(text: str) -> dict:
    """Tokenize lowercase text using tiktoken and return term frequency (TF) sparse vector."""
    if not text:
        return {"indices": [], "values": []}
    enc = tiktoken.get_encoding("cl100k_base")
    words = text.lower().split()
    tokens = []
    for w in words:
        tokens.extend(enc.encode(w))
    counts = Counter(tokens)
    indices = sorted(counts.keys())
    values = [float(counts[idx]) for idx in indices]
    return {"indices": indices, "values": values}

async def upsert_term_vectors(
    parent_id: str,
    user_id: str,
    name: str,
    synonyms: List[str],
    tags: List[str],
    is_location: bool,
    generated_desc: str
):
    """Upsert main term and all its synonyms to Qdrant with dense and sparse vectors."""
    url = get_qdrant_url()
    client = AsyncQdrantClient(url=url)
    points = []
    
    try:
        from providers import llm_provider
        
        # 1. Main point (uses parent_id as the Qdrant point ID)
        dense_vector = await llm_provider.generate_embeddings(settings.EMBEDDING_MODEL_NAME, generated_desc or name)
        sparse_data = get_sparse_vector(name)
        
        main_payload = {
            "user_id": str(user_id),
            "parent_id": str(parent_id),
            "name": name,
            "generated_desc": generated_desc,
            "tags": tags or [],
            "is_location": is_location,
            "is_synonym": False
        }
        
        points.append(
            PointStruct(
                id=str(parent_id),
                vector={
                    "dense": dense_vector,
                    "sparse": SparseVector(
                        indices=sparse_data["indices"],
                        values=sparse_data["values"]
                    )
                },
                payload=main_payload
            )
        )
        
        # 2. Synonym points (use newly generated UUIDs)
        for syn in (synonyms or []):
            syn_str = str(syn).strip()
            if not syn_str:
                continue
                
            syn_id = str(uuid.uuid4())
            syn_desc = f"{syn_str}. Синоним для {name}."
            dense_vector_syn = await llm_provider.generate_embeddings(settings.EMBEDDING_MODEL_NAME, syn_desc)
            sparse_data_syn = get_sparse_vector(syn_str)
            
            syn_payload = {
                "user_id": str(user_id),
                "parent_id": str(parent_id),
                "name": syn_str,
                "generated_desc": syn_desc,
                "tags": tags or [],
                "is_location": is_location,
                "is_synonym": True
            }
            
            points.append(
                PointStruct(
                    id=syn_id,
                    vector={
                        "dense": dense_vector_syn,
                        "sparse": SparseVector(
                            indices=sparse_data_syn["indices"],
                            values=sparse_data_syn["values"]
                        )
                    },
                    payload=syn_payload
                )
            )
            
        await client.upsert(
            collection_name="items",
            points=points
        )
        logger.info(f"Qdrant: Indexed term {parent_id} ({name}) with {len(points) - 1} synonyms")
    except Exception as e:
        logger.error(f"Failed to upsert term vectors to Qdrant: {e}")
    finally:
        await client.close()

async def delete_item_vector(item_id: str):
    """Delete all points associated with the given parent_id from Qdrant."""
    url = get_qdrant_url()
    client = AsyncQdrantClient(url=url)
    try:
        await client.delete(
            collection_name="items",
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="parent_id",
                        match=MatchValue(value=str(item_id))
                    )
                ]
            )
        )
        logger.debug(f"Deleted all Qdrant vectors for parent {item_id}")
    except Exception as e:
        logger.error(f"Failed to delete vector from Qdrant: {e}")
    finally:
        await client.close()

async def hybrid_search_items_locations(
    user_id: str,
    query: str,
    is_location: bool,
    query_tags: List[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Perform hybrid dense/sparse search in Qdrant with synonym grouping & score aggregation."""
    if not query:
        return []
        
    url = get_qdrant_url()
    client = AsyncQdrantClient(url=url)
    
    try:
        from providers import llm_provider
        
        # 1. Generate query vectors
        dense_vector = await llm_provider.generate_embeddings(settings.EMBEDDING_MODEL_NAME, query)
        sparse_data = get_sparse_vector(query)
        
        # 2. Build filters (User Isolation & Entity Type)
        must_conditions = [
            FieldCondition(key="user_id", match=MatchValue(value=str(user_id))),
            FieldCondition(key="is_location", match=MatchValue(value=is_location))
        ]
        
        # Tag intersection: require at least one matching tag if query_tags provided
        if query_tags:
            tag_filters = [
                FieldCondition(key="tags", match=MatchValue(value=t))
                for t in query_tags
            ]
            must_conditions.append(Filter(should=tag_filters))
            
        filter_cond = Filter(must=must_conditions)
        
        # 3. Perform prefetch & RRF fusion query
        prefetch = [
            Prefetch(
                query=dense_vector,
                using="dense",
                filter=filter_cond,
                limit=limit * 3
            ),
            Prefetch(
                query=SparseVector(
                    indices=sparse_data["indices"],
                    values=sparse_data["values"]
                ),
                using="sparse",
                filter=filter_cond,
                limit=limit * 3
            )
        ]
        
        res = await client.query_points(
            collection_name="items",
            prefetch=prefetch,
            query=FusionQuery(fusion=Fusion.RRF),
            limit=limit * 3
        )
        
        # 4. Synonym aggregation / Grouping by parent_id
        grouped = defaultdict(list)
        for hit in res.points:
            parent_id = hit.payload.get("parent_id")
            if parent_id:
                grouped[parent_id].append(hit)
                
        results = []
        for parent_id, hits in grouped.items():
            # Synonym-aware: take the maximum score from matching synonym/term points
            max_hit = max(hits, key=lambda h: h.score)
            results.append({
                "parent_id": parent_id,
                "name": max_hit.payload.get("name"),
                "is_location": max_hit.payload.get("is_location"),
                "tags": max_hit.payload.get("tags") or [],
                "description": max_hit.payload.get("generated_desc"),
                "score": max_hit.score
            })
            
        # 5. Sort by aggregated score in descending order
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]
        
    except Exception as e:
        logger.error(f"Failed hybrid search in Qdrant: {e}")
        return []
    finally:
        await client.close()

# ==========================================
# BACKWARD COMPATIBILITY WRAPPERS
# ==========================================

async def upsert_item_vector(item_id: str, user_id: str, vector: List[float], payload: Dict[str, Any]):
    """Wrapper mapping old upsert_item_vector to upsert_term_vectors."""
    name = payload.get("name") or "Item"
    generated_desc = payload.get("generated_desc") or name
    # Fallback to no synonyms, no tags, not a location
    await upsert_term_vectors(
        parent_id=item_id,
        user_id=user_id,
        name=name,
        synonyms=[],
        tags=[],
        is_location=False,
        generated_desc=generated_desc
    )

async def semantic_search_items(user_id: str, query_vector: List[float], limit: int = 10) -> List[str]:
    """Wrapper mapping old semantic_search_items to hybrid_search_items_locations using dummy text query."""
    # Since old code passed query_vector, we can't extract the original query text.
    # We will search with a dummy query or fallback.
    # However, all new code uses hybrid_search_items_locations directly.
    # To keep this wrapper functional, we perform a fallback search using dense-only query.
    url = get_qdrant_url()
    client = AsyncQdrantClient(url=url)
    try:
        result = await client.search(
            collection_name="items",
            query_vector=("dense", query_vector),
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="user_id",
                        match=MatchValue(value=str(user_id))
                    ),
                    FieldCondition(
                        key="is_location",
                        match=MatchValue(value=False)
                    )
                ]
            ),
            limit=limit
        )
        return [hit.payload.get("parent_id") or hit.id for hit in result]
    except Exception as e:
        logger.error(f"Failed semantic search fallback wrapper: {e}")
        return []
    finally:
        await client.close()
