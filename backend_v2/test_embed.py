import asyncio
from services.embedding_service import get_embedding_service

def test():
    svc = get_embedding_service()
    emb = svc.generate_embedding("hello world")
    print(f"Embedding length: {len(emb)}, type: {type(emb[0])}")

test()
