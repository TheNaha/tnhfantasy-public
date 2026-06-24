import asyncio
from sqlmodel import Session
from infrastructure.database import engine
from services.model_service import ModelServiceV2

async def main():
    with Session(engine) as session:
        service = ModelServiceV2(session)
        models = await service.list_models_by_directory("loras")
        ids = [m["id"] for m in models]
        print("Model IDs:", ids)
        if 296 in ids:
            print("296 is present!")
        else:
            print("296 is MISSING!")

asyncio.run(main())
