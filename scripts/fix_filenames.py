import os
import glob
import re
import shutil
from datetime import datetime

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'output')))
def fix_filenames():
    files = []
    # Find all PNG files in the output directory and subdirectories
    for pattern in ['*.png', '**/*.png']:
        files.extend(glob.glob(os.path.join(OUTPUT_DIR, pattern), recursive=True))
    
    # Filter out valid files ignoring thumbnails and json
    valid_files = [f for f in set(files) if not (f.endswith('.json') or f.endswith('.preview.png') or '.thumb.' in f or '.medium.' in f or '/thumb/' in f.replace('\\', '/'))]
    
    count = 0
    skipped = 0
    errors = 0
    
    for filepath in valid_files:
        dirname = os.path.dirname(filepath)
        basename = os.path.basename(filepath)
        
        # Match expected filename pattern
        match = re.search(r'Generated_(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})', basename)
        if not match:
            skipped += 1
            print(f"Skipping (no match): {basename}")
            continue
            
        # Get actual file modification time in local timezone
        try:
            mtime = os.path.getmtime(filepath)
            dt = datetime.fromtimestamp(mtime)
            
            # Target directory structure YYYY/MM/DD
            target_dir = os.path.join(OUTPUT_DIR, dt.strftime('%Y'), dt.strftime('%m'), dt.strftime('%d'))
            os.makedirs(target_dir, exist_ok=True)
            
            # Format the new filename
            new_date_str = dt.strftime('%Y-%m-%d_%H-%M-%S')
            old_date_str = f"{match.group(1)}-{match.group(2)}-{match.group(3)}_{match.group(4)}-{match.group(5)}-{match.group(6)}"
            
            new_basename = basename.replace(old_date_str, new_date_str)
            new_filepath = os.path.join(target_dir, new_basename)
            
            if new_filepath == filepath:
                skipped += 1
                continue # Already in correct folder and name
                
            # Avoid overwriting if a file with the exact same second already exists
            original_new_filepath = new_filepath
            suffix = 1
            while os.path.exists(new_filepath) and filepath != new_filepath:
                name_parts = os.path.splitext(original_new_filepath)
                new_filepath = f"{name_parts[0]}_fix{suffix}{name_parts[1]}"
                suffix += 1
                
            print(f"Moving/Renaming: {basename} -> {os.path.basename(new_filepath)} in {target_dir}")
            shutil.move(filepath, new_filepath)
            
            # Check if there's a corresponding JSON or preview file and move/rename it too
            base_no_ext = os.path.splitext(filepath)[0]
            new_base_no_ext = os.path.splitext(new_filepath)[0]
            
            # Rename corresponding json
            if os.path.exists(base_no_ext + '.json'):
                shutil.move(base_no_ext + '.json', new_base_no_ext + '.json')
                
            # Rename preview
            prev_name = basename.replace('.png', '.preview.png')
            if os.path.exists(os.path.join(dirname, prev_name)):
                shutil.move(os.path.join(dirname, prev_name), os.path.join(target_dir, os.path.basename(new_filepath).replace('.png', '.preview.png')))
                
            count += 1
        except Exception as e:
            errors += 1
            print(f"Error processing {basename}: {e}")
            
    print(f"\n--- Summary ---")
    print(f"Total processed: {len(valid_files)}")
    print(f"Moved/Renamed: {count}")
    print(f"Skipped (already correct or unrecognized): {skipped}")
    print(f"Errors: {errors}")

if __name__ == '__main__':
    print(f"Starting to fix filenames and paths in {OUTPUT_DIR}...")
    fix_filenames()
    print("Done!")
