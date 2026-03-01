import re

with open('backend_v2/api/routes/providers.py', 'r') as f:
    content = f.read()

target = """    service = get_image_service()

    result = await service.save_generated_image(
        image_data=image_data,
        metadata=request.metadata,
        job_id=request.job_id,
        filename=request.filename,
        batch_index=request.batch_index
    )

    return result"""

replacement = """    from services.job_service import JobService
    from core.entities import JobStatus
    from infrastructure.database import get_session_context

    # 1. Set job to POST_PROCESSING if job_id provided
    if request.job_id:
        try:
            async with get_session_context() as session:
                job_service = JobService(session)
                await job_service.update_job(request.job_id, status=JobStatus.POST_PROCESSING)
        except Exception as e:
            logger.error(f"Failed to update job to post-processing: {e}")

    service = get_image_service()

    # 2. Save image and generate thumbnails (synchronous inside but async def)
    result = await service.save_generated_image(
        image_data=image_data,
        metadata=request.metadata,
        job_id=request.job_id,
        filename=request.filename,
        batch_index=request.batch_index
    )

    # 3. Synchronously add the file to the GalleryIndexer to prevent race conditions
    try:
        from api.routes.statistics import gallery_indexer
        gallery_indexer.add_file(result['path'])
    except Exception as e:
        logger.error(f"Failed to add file to gallery indexer: {e}")

    return result"""

content = content.replace(target, replacement)

with open('backend_v2/api/routes/providers.py', 'w') as f:
    f.write(content)
