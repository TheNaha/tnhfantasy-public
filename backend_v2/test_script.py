import asyncio
from sqlmodel import Session
from infrastructure.database import engine
from services.model_service import ModelServiceV2

async def main():
    with Session(engine) as session:
        service = ModelServiceV2(session)
        models = await service.list_models_by_directory("loras")
        for m in models:
            if m["id"] == 296:
                print("FOUND 296:")
                import json
                print(json.dumps(m, indent=2))

asyncio.run(main())
