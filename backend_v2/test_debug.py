import asyncio
from sqlmodel import Session, create_engine, SQLModel
from config import SQLITE_URL
from tests.conftest import _DummyContainerManager, _DummyContainersClient, sample_provider_data
from services.provider_service import ProviderService

async def debug():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    service = ProviderService(session)
    provider_data = {
        "id": "stuck-provider-state",
        "type": "modal",
        "priority": 1,
        "config": {}
    }
    await service.create_provider(provider_data)
    provider = await service.get_provider("stuck-provider-state")
    
    stuck_state = service.deploy_service._build_deploy_state(
        provider_id=provider.id,
        provider_type=provider.type,
        status="deploying",
        attempt_id="179eec65-3a78-4f7f-8c96-4a12572efa5e",
        started_at="2026-06-22T00:00:00Z",
        message="Deployment started",
        steps=[],
    )
    print("Before persist:", provider.config)
    await service.deploy_service._persist_deploy_state(provider, stuck_state)
    print("After persist obj:", provider.config)
    
    provider2 = await service.get_provider("stuck-provider-state")
    print("After persist db:", provider2.config)
    
    state = service.deploy_service.get_provider_deploy_state(provider2)
    print("State:", await state)

asyncio.run(debug())
