#!/usr/bin/env python3
"""
Migration script for output system overhaul.

This script:
1. Deletes all .thumb.png files (no longer needed, ~100KB each)
2. Deletes all .medium.png files (will be regenerated as WebP)
3. Optionally embeds sidecar .json metadata into PNG files and deletes sidecar

Usage:
    python migrate_output.py --delete-thumbs --delete-medium
    python migrate_output.py --embed-metadata --delete-sidecar
    python migrate_output.py --all  # Do everything
    python migrate_output.py --dry-run  # Preview only
"""

import os
import sys
import json
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
except ImportError:
    print("Error: Pillow not installed. Run: pip install Pillow")
    sys.exit(1)


def get_output_dir() -> Path:
    """Get the output directory path."""
    # Output is in parent project folder: comfyui/output (not backend_v2/output)
    default_path = os.path.join(os.path.dirname(__file__), "../../output")
    return Path(os.environ.get("OUTPUT_DIR", default_path))


def find_thumb_files(output_dir: Path) -> list:
    """Find all .thumb.png files (searches recursively in subdirectories)."""
    return list(output_dir.rglob("*.thumb.png"))


def find_medium_files(output_dir: Path) -> list:
    """Find all .medium.png files (searches recursively in subdirectories)."""
    return list(output_dir.rglob("*.medium.png"))


def find_sidecar_json_files(output_dir: Path) -> list:
    """Find all sidecar .json files (e.g., image.png.json, searches recursively)."""
    json_files = []
    for json_path in output_dir.rglob("*.png.json"):
        # Check if corresponding image exists
        image_path = Path(str(json_path)[:-5])  # Remove .json
        if image_path.exists():
            json_files.append((image_path, json_path))
    return json_files


def delete_files(files: list, dry_run: bool = False) -> tuple:
    """Delete list of files. Returns (deleted_count, total_size)."""
    deleted = 0
    total_size = 0
    
    for f in files:
        path = f if isinstance(f, Path) else f[0]
        try:
            size = path.stat().st_size
            if dry_run:
                print(f"  [DRY RUN] Would delete: {path.name} ({size / 1024:.1f}KB)")
            else:
                path.unlink()
                print(f"  Deleted: {path.name} ({size / 1024:.1f}KB)")
            deleted += 1
            total_size += size
        except Exception as e:
            print(f"  Error deleting {path}: {e}")
    
    return deleted, total_size


def embed_metadata_in_png(image_path: Path, json_path: Path) -> bool:
    """Embed JSON metadata into PNG file."""
    try:
        # Read existing metadata
        with open(json_path, 'r') as f:
            metadata = json.load(f)
        
        # Read image
        with Image.open(image_path) as img:
            # Create new PngInfo
            pnginfo = PngInfo()
            
            # Embed individual fields for compatibility
            if "workflow" in metadata:
                pnginfo.add_text("workflow", json.dumps(metadata["workflow"]))
            if "prompt" in metadata:
                pnginfo.add_text("prompt", json.dumps(metadata["prompt"]))
            
            # Embed full metadata
            pnginfo.add_text("comfy_metadata", json.dumps(metadata))
            
            # Save back with embedded metadata
            img.save(image_path, pnginfo=pnginfo)
        
        return True
    except Exception as e:
        print(f"  Error embedding metadata in {image_path.name}: {e}")
        return False


def find_images_without_webp_thumbnail(output_dir: Path, thumb_dir: Path) -> list:
    """Find original images that don't have a WebP thumbnail (searches recursively)."""
    images_needing_thumbs = []
    
    # Find all original PNG files recursively (not thumbs, not medium)
    for image_path in output_dir.rglob("*.png"):
        name = image_path.stem
        # Skip if it's a thumbnail itself
        if name.endswith('.thumb') or name.endswith('.medium'):
            continue
        # Skip if in thumb directory
        if 'thumb' in str(image_path.parent):
            continue
        
        # Check if WebP thumbnail exists anywhere in thumb directory
        webp_exists = False
        for webp in thumb_dir.rglob(f"{name}.webp"):
            webp_exists = True
            break
        
        if not webp_exists:
            images_needing_thumbs.append(image_path)
    
    return images_needing_thumbs


def regenerate_thumbnail(image_path: Path, thumb_dir: Path, dry_run: bool = False) -> bool:
    """Generate WebP thumbnail for an image."""
    try:
        from datetime import datetime
        
        # Get date from filename or file mtime
        name = image_path.stem
        
        # Create date-based thumb directory
        mtime = datetime.fromtimestamp(image_path.stat().st_mtime)
        date_path = thumb_dir / str(mtime.year) / f"{mtime.month:02d}" / f"{mtime.day:02d}"
        
        if dry_run:
            print(f"  [DRY RUN] Would regenerate: {name}.webp -> {date_path}")
            return True
        
        date_path.mkdir(parents=True, exist_ok=True)
        
        # Generate thumbnail
        with Image.open(image_path) as img:
            # Convert RGBA to RGB if needed
            if img.mode == 'RGBA':
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize to medium (512px max)
            img.thumbnail((512, 512), Image.Resampling.LANCZOS)
            
            # Save as WebP
            webp_path = date_path / f"{name}.webp"
            img.save(webp_path, format='WEBP', quality=85, method=4)
            
        print(f"  Generated: {name}.webp")
        return True
    except Exception as e:
        print(f"  Error regenerating {image_path.name}: {e}")
        return False


def find_flat_original_images(output_dir: Path) -> list:
    """Find original images in flat output directory (not in date subdirectories)."""
    flat_images = []
    
    # Only search in root, not subdirectories - these are legacy images to reorganize
    for image_path in output_dir.glob("*.png"):
        name = image_path.stem
        # Skip if it's a thumbnail itself
        if name.endswith('.thumb') or name.endswith('.medium'):
            continue
        flat_images.append(image_path)
    
    return flat_images


def reorganize_image(image_path: Path, output_dir: Path, dry_run: bool = False) -> bool:
    """Move an image to date-based directory structure."""
    try:
        from datetime import datetime
        import shutil
        import re
        
        name = image_path.name
        
        # Parse date from filename (e.g., Generated_2025-12-07_14-30-00_00001_.png)
        date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', name)
        if date_match:
            year, month, day = date_match.groups()
        else:
            # Fallback to file mtime
            mtime = datetime.fromtimestamp(image_path.stat().st_mtime)
            year, month, day = str(mtime.year), f"{mtime.month:02d}", f"{mtime.day:02d}"
        
        date_path = output_dir / year / month / day
        new_path = date_path / name
        
        if dry_run:
            print(f"  [DRY RUN] Would move: {name} -> {year}/{month}/{day}/")
            return True
        
        # Create directory and move file
        date_path.mkdir(parents=True, exist_ok=True)
        shutil.move(str(image_path), str(new_path))
        
        # Also move sidecar JSON if exists
        json_path = Path(str(image_path) + ".json")
        if json_path.exists():
            new_json_path = date_path / (name + ".json")
            shutil.move(str(json_path), str(new_json_path))
        
        print(f"  Moved: {name} -> {year}/{month}/{day}/")
        return True
    except Exception as e:
        print(f"  Error moving {image_path.name}: {e}")
        return False


def restore_file_mtime(file_path: Path, dry_run: bool = False) -> bool:
    """Restore file modification time based on date in filename."""
    try:
        from datetime import datetime
        import re
        
        name = file_path.name
        
        # Parse date and time from filename (e.g., Generated_2025-12-07_14-30-00_00001_.png)
        datetime_match = re.search(r'(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})', name)
        if datetime_match:
            year, month, day, hour, minute, second = map(int, datetime_match.groups())
            parsed_dt = datetime(year, month, day, hour, minute, second)
        else:
            # Try just date
            date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', name)
            if date_match:
                year, month, day = map(int, date_match.groups())
                parsed_dt = datetime(year, month, day, 12, 0, 0)  # Default to noon
            else:
                print(f"  Skipped: {name} (no date in filename)")
                return False
        
        timestamp = parsed_dt.timestamp()
        
        if dry_run:
            current_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            print(f"  [DRY RUN] Would restore mtime: {name} {current_mtime} -> {parsed_dt}")
            return True
        
        import os
        os.utime(file_path, (timestamp, timestamp))
        print(f"  Restored mtime: {name} -> {parsed_dt}")
        return True
    except Exception as e:
        print(f"  Error restoring mtime for {file_path.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Migrate output files to new structure")
    parser.add_argument("--delete-thumbs", action="store_true", help="Delete all .thumb.png files")
    parser.add_argument("--delete-medium", action="store_true", help="Delete all .medium.png files")
    parser.add_argument("--regenerate-thumbnails", action="store_true", help="Regenerate WebP thumbnails for existing images")
    parser.add_argument("--reorganize-images", action="store_true", help="Move original images to date-based directories")
    parser.add_argument("--restore-mtime", action="store_true", help="Restore file modification time from filename date")
    parser.add_argument("--embed-metadata", action="store_true", help="Embed sidecar JSON into PNG files")
    parser.add_argument("--delete-sidecar", action="store_true", help="Delete sidecar .json files after embedding")
    parser.add_argument("--all", action="store_true", help="Do all migration steps")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without making them")
    
    args = parser.parse_args()
    
    if args.all:
        args.delete_thumbs = True
        args.delete_medium = True
        args.reorganize_images = True
        args.restore_mtime = True
        args.regenerate_thumbnails = True
        args.embed_metadata = True
        args.delete_sidecar = True
    
    if not any([args.delete_thumbs, args.delete_medium, args.embed_metadata, args.regenerate_thumbnails, args.reorganize_images, args.restore_mtime]):
        parser.print_help()
        print("\nNo actions specified. Use --help for usage.")
        return

    
    output_dir = get_output_dir()
    print(f"Output directory: {output_dir}")
    
    if not output_dir.exists():
        print(f"Error: Output directory not found: {output_dir}")
        sys.exit(1)
    
    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]\n")
    
    total_deleted = 0
    total_size_saved = 0
    
    # Delete thumb files
    if args.delete_thumbs:
        print("\n=== Deleting .thumb.png files ===")
        thumb_files = find_thumb_files(output_dir)
        print(f"Found {len(thumb_files)} .thumb.png files")
        
        deleted, size = delete_files(thumb_files, args.dry_run)
        total_deleted += deleted
        total_size_saved += size
        print(f"{'Would delete' if args.dry_run else 'Deleted'} {deleted} files, {size / 1024 / 1024:.2f}MB saved")
    
    # Delete medium files
    if args.delete_medium:
        print("\n=== Deleting .medium.png files ===")
        medium_files = find_medium_files(output_dir)
        print(f"Found {len(medium_files)} .medium.png files")
        
        deleted, size = delete_files(medium_files, args.dry_run)
        total_deleted += deleted
        total_size_saved += size
        print(f"{'Would delete' if args.dry_run else 'Deleted'} {deleted} files, {size / 1024 / 1024:.2f}MB saved")
    
    # Reorganize original images into date-based directories
    if args.reorganize_images:
        print("\n=== Reorganizing original images to date-based directories ===")
        flat_images = find_flat_original_images(output_dir)
        print(f"Found {len(flat_images)} images in flat directory")
        
        moved = 0
        for image_path in flat_images:
            if reorganize_image(image_path, output_dir, args.dry_run):
                moved += 1
        
        print(f"{'Would move' if args.dry_run else 'Moved'} {moved} images to date-based directories")
    
    # Restore modification times from filename
    if args.restore_mtime:
        print("\n=== Restoring modification times from filename ====")
        # Find all PNG files recursively
        all_pngs = list(output_dir.rglob("*.png"))
        # Filter out thumbnails
        all_pngs = [p for p in all_pngs if not (p.stem.endswith('.thumb') or p.stem.endswith('.medium'))]
        print(f"Found {len(all_pngs)} images to restore mtime")
        
        restored = 0
        for image_path in all_pngs:
            if restore_file_mtime(image_path, args.dry_run):
                restored += 1
        
        print(f"{'Would restore' if args.dry_run else 'Restored'} mtime for {restored} images")
    
    # Regenerate thumbnails as WebP
    if args.regenerate_thumbnails:
        print("\n=== Regenerating WebP thumbnails ===")
        thumb_dir = output_dir / "thumb"
        images_to_process = find_images_without_webp_thumbnail(output_dir, thumb_dir)
        print(f"Found {len(images_to_process)} images needing WebP thumbnails")
        
        regenerated = 0
        for image_path in images_to_process:
            if regenerate_thumbnail(image_path, thumb_dir, args.dry_run):
                regenerated += 1
        
        print(f"{'Would regenerate' if args.dry_run else 'Regenerated'} {regenerated} WebP thumbnails")
    
    # Embed metadata
    if args.embed_metadata:
        print("\n=== Embedding sidecar JSON into PNG files ===")
        pairs = find_sidecar_json_files(output_dir)
        print(f"Found {len(pairs)} image+JSON pairs")
        
        embedded = 0
        for image_path, json_path in pairs:
            if args.dry_run:
                print(f"  [DRY RUN] Would embed: {json_path.name} -> {image_path.name}")
                embedded += 1
            else:
                if embed_metadata_in_png(image_path, json_path):
                    print(f"  Embedded: {json_path.name} -> {image_path.name}")
                    embedded += 1
        
        print(f"{'Would embed' if args.dry_run else 'Embedded'} metadata into {embedded} images")
        
        # Delete sidecar files if requested
        if args.delete_sidecar and embedded > 0:
            print("\n=== Deleting sidecar .json files ===")
            json_files = [p[1] for p in pairs]
            deleted, size = delete_files([Path(f) for f in json_files], args.dry_run)
            total_deleted += deleted
            total_size_saved += size
            print(f"{'Would delete' if args.dry_run else 'Deleted'} {deleted} sidecar files, {size / 1024 / 1024:.2f}MB saved")
    
    # Summary
    print("\n" + "=" * 50)
    print(f"{'PREVIEW' if args.dry_run else 'SUMMARY'}:")
    print(f"  {'Would delete' if args.dry_run else 'Deleted'}: {total_deleted} files")
    print(f"  Storage saved: {total_size_saved / 1024 / 1024:.2f}MB")
    
    if args.dry_run:
        print("\nRun without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
