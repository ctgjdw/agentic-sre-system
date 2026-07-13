from sre_gateway.llm.embeddings import hash_embedding
from sre_gateway.retrieval import index_runbook, search_runbooks


async def _embed(texts):
    return [hash_embedding(t) for t in texts]


async def test_index_then_search_finds_exact_match(db):
    await index_runbook(db, _embed, title="Keycloak login outage",
                        body_md="restart keycloak", source_case_id=None, tags=["keycloak"])
    await index_runbook(db, _embed, title="OpenSearch disk pressure",
                        body_md="prune indices", source_case_id=None, tags=[])
    hits = await search_runbooks(db, _embed, "Keycloak login outage", k=1)
    assert hits[0]["title"] == "Keycloak login outage"
