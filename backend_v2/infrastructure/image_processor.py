# Image Processing Utility for BlurHash and Thumbnail Generation
# Handles thumbnail generation, BlurHash encoding, and metadata storage

import json
import os
from datetime import datetime

from PIL import Image
from PIL.PngImagePlugin import PngInfo

import config as app_config
from infrastructure.logging import get_logger

logger = get_logger("image_processor")


def get_output_path(base_dir: str = None, subdir: str = None, user_id: str = "default_user", workspace: str = "main") -> str:
    """
    Generate a partitioned, date-based output path.

    Layout: {base}/{user_id}/{workspace}/[subdir/]YYYY/MM/DD/

    The /{user_id}/ root partition future-proofs for (optional) multi-tenancy;
    the /{workspace}/ segment keeps Roleplay/Story/Image assets separated on
    disk so they can be scoped by the DB-backed assets index. A single-user
    deployment uses user_id="default_user".

    Args:
        base_dir: Base output directory (defaults to OUTPUT_DIR env or ./output)
        subdir: Optional subdirectory (e.g., 'thumb')
        user_id: Owner partition (default "default_user")
        workspace: Workspace partition (main / roleplay / story)

    Returns:
        Path to the date-based directory (created if doesn't exist)
    """
    if base_dir is None:
        base_dir = app_config.settings.output_dir

    # Partition: /{user_id}/{workspace}/  (skip empty segments)
    partition = os.path.join(base_dir, user_id or "default_user", workspace or "main")
    if subdir:
        partition = os.path.join(partition, subdir)

    if app_config.get_output_date_hierarchy():
        now = datetime.now()
        date_path = os.path.join(partition, str(now.year), f"{now.month:02d}", f"{now.day:02d}")
    else:
        date_path = partition

    os.makedirs(date_path, exist_ok=True)
    return date_path


def read_png_metadata(path: str) -> dict:
    """Read embedded generation metadata back out of a saved PNG (best-effort)."""
    import json as _json
    try:
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo
        with Image.open(path) as img:
            raw = img.info.get("comfy_metadata") or img.info.get("parameters") or img.info.get("Comment")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "ignore")
            if not raw:
                return {}
            # comfy_metadata is JSON; parameters/Comment are free text.
            try:
                return _json.loads(raw)
            except Exception:
                return {"parameters": raw}
    except Exception:
        return {}


def get_thumb_output_path(base_dir: str = None, user_id: str = "default_user", workspace: str = "main") -> str:
    """Thumbnails mirror the partitioned layout under a `thumb` subdir."""
    return get_output_path(base_dir=base_dir, subdir="thumb", user_id=user_id, workspace=workspace)


def save_image_with_metadata(image: Image.Image, path: str, metadata: dict) -> str:
    """
    Save PNG with embedded JSON metadata in text chunks.
    
    Args:
        image: PIL Image to save
        path: Output path for the image
        metadata: Dict containing workflow, prompt, and other metadata
    
    Returns:
        Path to saved image
    """
    pnginfo = PngInfo()
    
    # Embed individual fields for compatibility with other tools
    if "workflow" in metadata:
        pnginfo.add_text("workflow", json.dumps(metadata["workflow"]))
    if "prompt" in metadata:
        pnginfo.add_text("prompt", json.dumps(metadata["prompt"]))
    
    # Embed full metadata as compressed JSON for our use
    full_metadata_str = json.dumps(metadata)
    pnginfo.add_text("comfy_metadata", full_metadata_str)
    
    # Save with embedded metadata
    image.save(path, pnginfo=pnginfo)
    logger.info("image_saved_with_metadata", path=path)
    
    return path


def write_metadata_sidecar(path: str, metadata: dict) -> str:
    """Write metadata to the legacy sidecar JSON file used as a compatibility fallback."""
    sidecar_path = f"{path}.json"
    with open(sidecar_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f)
    return sidecar_path


def read_image_metadata(path: str) -> dict:
    """
    Read metadata from PNG file (embedded) or fallback to sidecar .json.
    
    Args:
        path: Path to the image file
    
    Returns:
        Metadata dict (may be empty if not found)
    """
    metadata = {}
    
    try:
        with Image.open(path) as img:
            # Try to read embedded metadata
            metadata_str = img.info.get("comfy_metadata")
            if metadata_str:
                metadata = json.loads(metadata_str)
                return metadata
    except Exception as e:
        logger.debug("embedded_metadata_read_failed", path=path, error=str(e))
    
    # Fallback to sidecar .json file for legacy images
    json_path = f"{path}.json"
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                metadata = json.load(f)
        except Exception as e:
            logger.debug("sidecar_json_read_failed", path=json_path, error=str(e))
    
    return metadata


def generate_thumbnails(image_path: str, sizes: dict = None, output_base_dir: str = None, user_id: str = "default_user", workspace: str = "main") -> dict:
    """
    Generate thumbnails from an image and save to a partitioned thumb directory.

    Args:
        image_path: Path to the original image
        sizes: Dict of {suffix: max_dimension}, e.g. {'medium': 512}
        output_base_dir: Base output directory (uses OUTPUT_DIR env if not specified)
        user_id: Owner partition (default "default_user")
        workspace: Workspace partition (main / roleplay / story)

    Returns:
        Dict of {suffix: thumbnail_path}
    """
    if sizes is None:
        sizes = app_config.get_thumbnail_sizes()
    
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    
    # Get original filename (without path and extension)
    original_filename = os.path.splitext(os.path.basename(image_path))[0]
    
    # Get thumbnail format and directory
    thumb_format = app_config.get_thumbnail_format()  # webp
    thumb_dir_name = app_config.get_thumbnail_directory()  # 'thumb'
    quality = app_config.get_thumbnail_quality()
    
    # Get thumb output directory (output/thumb/YYYY/MM/DD/)
    thumb_output_dir = get_output_path(output_base_dir, subdir=thumb_dir_name, user_id=user_id, workspace=workspace)
    
    thumbnail_paths = {}
    
    for suffix, max_size in sizes.items():
        # Open a fresh copy for each size to avoid PIL's thumbnail() mutation
        img = Image.open(image_path)
        
        # Convert RGBA to RGB if needed (for WebP/JPEG compatibility)
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])  # Use alpha channel as mask
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Calculate new size maintaining aspect ratio
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        # Build thumbnail path in thumb directory with proper format
        # e.g., output/thumb/2025/12/07/Generated_2025-12-07_23-54-29_00001.webp
        thumb_filename = f"{original_filename}.{thumb_format}"
        thumb_path = os.path.join(thumb_output_dir, thumb_filename)
        
        # Save thumbnail in configured format
        if thumb_format == 'webp':
            img.save(thumb_path, format='WEBP', quality=quality, method=4)
        elif thumb_format == 'jpg' or thumb_format == 'jpeg':
            img.save(thumb_path, format='JPEG', quality=quality, optimize=True)
        else:
            img.save(thumb_path, quality=quality, optimize=True)
        
        thumbnail_paths[suffix] = thumb_path
        
        logger.info("thumbnail_generated", suffix=suffix, format=thumb_format, path=thumb_path)
    
    return thumbnail_paths


def encode_blurhash(image_path: str, components_x: int = None, components_y: int = None) -> str:
    """
    Generate BlurHash from an image.
    
    Args:
        image_path: Path to the image
        components_x: Number of components in X direction (4 is good default)
        components_y: Number of components in Y direction (3 is good default)
    
    Returns:
        BlurHash string (e.g., "LEHV6nWB2yk8pyo0adR*.7kCMdnj")
    """
    try:
        import blurhash
        import numpy as np
    except ImportError:
        logger.warning("blurhash_import_missing")
        return ""
    
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    
    # Get components from config if not provided
    if components_x is None or components_y is None:
        components_x, components_y = app_config.get_blurhash_components()
    
    # Open and resize for faster processing (blurhash doesn't need full res)
    img = Image.open(image_path)
    
    # Convert to RGB
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    # Resize to reasonable size for hash generation (faster)
    max_size = app_config.get_blurhash_resize_max()
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    
    # Convert PIL Image to numpy array (blurhash expects this format)
    img_array = np.array(img)
    
    # Encode blurhash
    hash_value = blurhash.encode(img_array, components_x=components_x, components_y=components_y)
    
    logger.info("blurhash_generated", hash_value=hash_value)
    return hash_value


def get_image_dimensions(image_path: str) -> tuple[int, int]:
    """
    Get image dimensions without loading full image into memory.
    
    Args:
        image_path: Path to the image
        
    Returns:
        Tuple of (width, height)
    """
    with Image.open(image_path) as img:
        return img.size


def resize_image(image_path: str, max_dimension: int, output_path: str = None, quality: int = 85) -> str:
    """
    Resize an image maintaining aspect ratio.
    
    Args:
        image_path: Path to the original image
        max_dimension: Maximum width or height
        output_path: Output path (if None, overwrites original)
        quality: JPEG quality (1-100)
        
    Returns:
        Path to the resized image
    """
    if output_path is None:
        output_path = image_path
    
    img = Image.open(image_path)
    
    # Convert RGBA to RGB if needed
    if img.mode == 'RGBA':
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')
    
    # Resize maintaining aspect ratio
    img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    
    # Save
    img.save(output_path, quality=quality, optimize=True)
    
    return output_path


def process_image(image_path: str, save_metadata: bool = True) -> dict:
    """
    Complete image processing: thumbnails + blurhash.
    
    Args:
        image_path: Path to the original image
        save_metadata: Whether to save metadata to .json file
    
    Returns:
        Dict containing:
        - thumbnails: {suffix: path}
        - blurhash: hash string
        - metadata_path: path to .json file (if saved)
    """
    logger.info("processing_image", path=image_path)
    
    # Generate thumbnails
    thumbnails = generate_thumbnails(image_path)
    
    # Generate blurhash
    hash_value = encode_blurhash(image_path)
    
    # Get dimensions
    width, height = get_image_dimensions(image_path)
    
    result = {
        'thumbnails': thumbnails,
        'blurhash': hash_value,
        'original': image_path,
        'width': width,
        'height': height
    }
    
    # Read existing sidecar metadata if present (for migration/legacy files)
    # Note: New images have metadata embedded in PNG chunks, not sidecar files
    if save_metadata:
        metadata_path = f"{image_path}.json"
        
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                # Add blurhash and thumbnail info to result (for legacy compatibility)
                result['legacy_metadata'] = metadata
            except Exception as e:
                logger.warning("sidecar_metadata_read_failed", error=str(e))
    
    return result


def process_directory(directory: str, pattern: str = "*.png", skip_existing: bool = True) -> list[str]:
    """
    Process all images in a directory that don't already have thumbnails.
    
    Args:
        directory: Directory to scan
        pattern: File pattern to match (default: *.png)
        skip_existing: Skip images that already have thumbnails
    
    Returns:
        List of processed image paths
    """
    import glob
    
    processed = []
    
    # Find all images
    image_files = glob.glob(os.path.join(directory, pattern))
    
    for image_path in image_files:
        base_name = os.path.basename(image_path)
        
        # Skip thumbnails and metadata files
        if '.thumb.' in base_name or '.medium.' in base_name or base_name.endswith('.json'):
            continue
        
        if skip_existing:
            # Check if thumbnails already exist
            base_path = os.path.splitext(image_path)[0]
            ext = os.path.splitext(image_path)[1]
            thumb_path = f"{base_path}.thumb{ext}"
            
            if os.path.exists(thumb_path):
                logger.info("thumbnail_skipped", filename=base_name)
                continue
        
        # Process image
        try:
            process_image(image_path)
            processed.append(image_path)
        except Exception as e:
            logger.error("image_processing_failed", filename=base_name, error=str(e))
    
    return processed


def cleanup_thumbnails(directory: str) -> int:
    """
    Remove all generated thumbnails from a directory.
    
    Args:
        directory: Directory to clean
        
    Returns:
        Number of files removed
    """
    import glob
    
    removed = 0
    
    # Find all thumbnail files
    for pattern in ['*.thumb.png', '*.medium.png', '*.thumb.jpg', '*.medium.jpg']:
        for filepath in glob.glob(os.path.join(directory, pattern)):
            try:
                os.remove(filepath)
                removed += 1
                logger.info("thumbnail_removed", path=filepath)
            except Exception as e:
                logger.error("thumbnail_remove_failed", path=filepath, error=str(e))
    
    return removed


if __name__ == "__main__":
    # Test/CLI usage
    import sys
    
    if len(sys.argv) > 1:
        path = sys.argv[1]
        
        if os.path.isfile(path):
            # Process single file
            result = process_image(path)
            print(f"\nProcessed: {path}")
            print(f"Thumbnails: {result['thumbnails']}")
            print(f"BlurHash: {result['blurhash']}")
        elif os.path.isdir(path):
            # Process directory
            processed = process_directory(path)
            print(f"\nProcessed {len(processed)} images")
        else:
            print("Error: Path not found")
    else:
        print("Usage: python image_processor.py <image_path_or_directory>")
