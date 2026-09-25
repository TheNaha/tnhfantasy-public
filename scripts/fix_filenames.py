import argparse
import glob
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "output"


def fix_filenames(output_dir: Path, dry_run: bool = False) -> tuple[int, int, int]:
    files = []
    for pattern in ("*.png", "**/*.png"):
        files.extend(glob.glob(str(output_dir / pattern), recursive=True))
    valid_files = [
        path for path in set(files)
        if not (path.endswith(".json") or path.endswith(".preview.png") or ".thumb." in path or ".medium." in path or "/thumb/" in path.replace("\\", "/"))
    ]

    moved = 0
    skipped = 0
    errors = 0
    for filepath in valid_files:
        basename = os.path.basename(filepath)
        match = re.search(r"Generated_(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})", basename)
        if not match:
            skipped += 1
            print(f"Skipping (no match): {basename}")
            continue
        try:
            modified_at = datetime.fromtimestamp(os.path.getmtime(filepath))
            target_dir = output_dir / modified_at.strftime("%Y") / modified_at.strftime("%m") / modified_at.strftime("%d")
            new_date = modified_at.strftime("%Y-%m-%d_%H-%M-%S")
            old_date = f"{match.group(1)}-{match.group(2)}-{match.group(3)}_{match.group(4)}-{match.group(5)}-{match.group(6)}"
            new_basename = basename.replace(old_date, new_date)
            new_filepath = target_dir / new_basename
            if new_filepath == Path(filepath):
                skipped += 1
                continue
            suffix = 1
            while new_filepath.exists() and new_filepath != Path(filepath):
                new_filepath = new_filepath.with_name(f"{new_filepath.stem}_fix{suffix}{new_filepath.suffix}")
                suffix += 1
            if dry_run:
                print(f"[DRY RUN] Would move: {filepath} -> {new_filepath}")
                moved += 1
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(filepath, new_filepath)
            old_base = Path(filepath).with_suffix("")
            new_base = new_filepath.with_suffix("")
            for sidecar in (Path(f"{old_base}.json"), old_base.with_name(old_base.name + ".preview.png")):
                if sidecar.exists():
                    suffix = ".json" if sidecar.suffix == ".json" else ".preview.png"
                    shutil.move(sidecar, new_base.with_name(new_base.name + suffix))
            moved += 1
        except Exception as exc:
            errors += 1
            print(f"Error processing {basename}: {exc}")
    return moved, skipped, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize generated output filenames")
    parser.add_argument("--output-dir", type=Path, default=Path(os.getenv("OUTPUT_DIR", DEFAULT_OUTPUT_DIR)))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    moved, skipped, errors = fix_filenames(args.output_dir, args.dry_run)
    print(f"Moved/Renamed: {moved}; Skipped: {skipped}; Errors: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
