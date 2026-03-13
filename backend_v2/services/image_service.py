# Image Service - Handle incoming generated images from workers
# Integrates with image_processor for metadata embedding, thumbnails, and blurhash

import os
import io
import base64
from datetime import datetime
from typing import Optional, Dict, Any
from PIL import Image

from infrastructure.image_processor import (
    get_output_path,
    save_image_with_metadata,
    generate_thumbnails,
    encode_blurhash,
    get_image_dimensions
)
from infrastructure.logging import get_logger

logger = get_logger("image_service")


class ImageService:
    """
    Service for handling generated images from workers.
    
    Responsibilities:
    - Save images to date-based output folder structure
    - Embed metadata in PNG chunks
    - Generate WebP thumbnails
    - Generate blurhash for placeholders
    """
    
    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or os.environ.get(
            "OUTPUT_DIR", 
            os.path.join(os.path.dirname(__file__), "../../output")
        )
    
    async def save_generated_image(
        self,
        image_data: bytes,
        metadata: Optional[Dict[str, Any]] = None,
        job_id: Optional[str] = None,
        filename: Optional[str] = None,
        batch_index: int = 0
    ) -> Dict[str, Any]:
        """
        Save a generated image with metadata embedding and thumbnail generation.
        
        Args:
            image_data: Raw PNG bytes
            metadata: Dict with workflow, prompt, generation params
            job_id: Associated job ID
            filename: Optional custom filename (auto-generated if not provided)
            batch_index: Index in batch (for multiple images in one job)
        
        Returns:
            Dict with:
            - path: Full path to saved image
            - relative_path: Path relative to output dir
            - filename: Just the filename
            - thumbnail: Path to thumbnail
            - blurhash: BlurHash string
            - width: Image width
            - height: Image height
        """
        metadata = metadata or {}
        
        # Generate filename with timestamp
        now = datetime.now()
        if not filename:
            job_suffix = f"_{job_id[:8]}" if job_id else ""
            batch_suffix = f"_{batch_index:05d}" if batch_index > 0 else "_00001"
            filename = f"Generated_{now.strftime('%Y-%m-%d_%H-%M-%S')}{job_suffix}{batch_suffix}_.png"
        
        # Get date-based output path (creates directory if needed)
        output_path = get_output_path(self.output_dir)
        full_path = os.path.join(output_path, filename)
        
        # Load image from bytes
        image = Image.open(io.BytesIO(image_data))
        
        # Add generation timestamp and job info to metadata
        save_metadata = {
            **metadata,
            "generated_at": now.isoformat(),
            "job_id": job_id,
        }
        
        # Save with embedded metadata
        save_image_with_metadata(image, full_path, save_metadata)
        
        # Generate WebP thumbnail (in thumb/YYYY/MM/DD/)
        try:
            thumbnails = generate_thumbnails(full_path, output_base_dir=self.output_dir)
            thumbnail_path = thumbnails.get("medium") or thumbnails.get("thumb")
        except Exception as e:
            logger.warning("thumbnail_generation_failed", error=str(e), path=full_path)
            thumbnail_path = None
        
        # Generate blurhash
        try:
            blurhash = encode_blurhash(full_path)
        except Exception as e:
            logger.warning("blurhash_generation_failed", error=str(e), path=full_path)
            blurhash = None
        
        # Get dimensions
        width, height = image.size
        
        # Calculate relative path from output dir
        relative_path = os.path.relpath(full_path, self.output_dir).replace("\\", "/")
        
        result = {
            "path": full_path,
            "relative_path": relative_path,
            "filename": filename,
            "width": width,
            "height": height,
        }
        
        if thumbnail_path:
            result["thumbnail"] = os.path.relpath(thumbnail_path, self.output_dir).replace("\\", "/")
        
        if blurhash:
            result["blurhash"] = blurhash
        
        logger.info("image_saved", filename=filename, width=width, height=height)
        
        return result
    
    async def save_images_from_base64(
        self,
        images: list,
        metadata: Optional[Dict[str, Any]] = None,
        job_id: Optional[str] = None
    ) -> list:
        """
        Save multiple base64-encoded images.
        
        Args:
            images: List of dicts with 'data' (base64 string) and optional 'filename'
            metadata: Shared metadata for all images
            job_id: Associated job ID
        
        Returns:
            List of save results
        """
        results = []
        
        for i, img_info in enumerate(images):
            # Handle both raw base64 and base64 in dict
            if isinstance(img_info, str):
                b64_data = img_info
                custom_filename = None
            else:
                b64_data = img_info.get("data", "")
                custom_filename = img_info.get("filename")
            
            # Decode base64
            try:
                image_data = base64.b64decode(b64_data)
            except Exception as e:
                logger.warning("image_decode_failed", index=i, error=str(e))
                continue
            
            # Save image
            result = await self.save_generated_image(
                image_data=image_data,
                metadata=metadata,
                job_id=job_id,
                filename=custom_filename,
                batch_index=i
            )
            results.append(result)
        
        return results


# Singleton instance
_image_service = None


def get_image_service() -> ImageService:
    """Get the singleton ImageService instance."""
    global _image_service
    if _image_service is None:
        _image_service = ImageService()
    return _image_service
