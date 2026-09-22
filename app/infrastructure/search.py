"""BM25 с фиксированной нормализацией длины; IDF вычисляет локальный Qdrant."""

import hashlib
import re
from collections import Counter

from qdrant_client import AsyncQdrantClient, models

from app.config import get_config

INDEX_SCHEMA = "bge-m3-1024.bm25-ru-1"


def sparse(text, *, query=False):
    terms = re.findall(r"[^\W_]+", text.casefold().replace("ё", "е"), re.UNICODE)
    counts = Counter(terms)
    weights = Counter()
    # Параметры версии индекса: k1=1.2, b=.75, опорная длина=128 токенов.
    for term, count in counts.items():
        index = int.from_bytes(hashlib.sha256(term.encode()).digest()[:4], "big")
        weights[index] += 1.0 if query else count * 2.2 / (count + 1.2 * (0.25 + 0.75 * len(terms) / 128))
    return models.SparseVector(indices=sorted(weights), values=[weights[i] for i in sorted(weights)])


def client():
    return AsyncQdrantClient(url=get_config().qdrant_url, timeout=10, check_compatibility=False)


async def initialize(qdrant, collection=None):
    name = collection or get_config().search_collection
    if not await qdrant.collection_exists(name):
        physical = name if collection else name + "_initial"
        await qdrant.create_collection(
            physical,
            vectors_config={
                "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE, on_disk=True)
            },
            sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
            hnsw_config=models.HnswConfigDiff(m=8),
            on_disk_payload=True,
        )
        for field in ("workspace_id", "lifecycle", "privacy_policy", "category"):
            await qdrant.create_payload_index(
                physical, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD
            )
        if not collection:
            await qdrant.update_collection_aliases(
                [
                    models.CreateAliasOperation(
                        create_alias=models.CreateAlias(collection_name=physical, alias_name=name)
                    )
                ]
            )
    return name


async def upsert(qdrant, item, text, vector, collection=None):
    name = await initialize(qdrant, collection)
    await qdrant.upsert(
        name,
        points=[
            models.PointStruct(
                id=item["id"],
                vector={"dense": vector, "sparse": sparse(text)},
                payload={
                    "entity_id": item["id"],
                    "workspace_id": item["workspace_id"],
                    "entity_version": item["search_revision"],
                    "index_schema_version": INDEX_SCHEMA,
                    "privacy_policy": item["privacy_policy"],
                    "lifecycle": item["lifecycle"],
                    "category": item["primary_category"],
                },
            )
        ],
        wait=True,
    )


async def retrieve(qdrant, workspace_id, query, dense, settings, *, egress_safe=False, category=None):
    filters = [
        models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id)),
        models.FieldCondition(key="lifecycle", match=models.MatchValue(value="active")),
    ]
    if egress_safe:
        filters.append(
            models.FieldCondition(key="privacy_policy", match=models.MatchValue(value="cloud_allowed"))
        )
    if category:
        filters.append(models.FieldCondition(key="category", match=models.MatchValue(value=category)))
    condition = models.Filter(must=filters)
    result = await qdrant.query_points(
        get_config().search_collection,
        prefetch=[
            models.Prefetch(
                query=dense, using="dense", filter=condition, limit=settings["search.dense_candidates"]
            ),
            models.Prefetch(
                query=sparse(query, query=True),
                using="sparse",
                filter=condition,
                limit=settings["search.sparse_candidates"],
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        query_filter=condition,
        limit=settings["search.final_candidates"],
        with_payload=True,
    )
    return [str(point.id) for point in result.points]
