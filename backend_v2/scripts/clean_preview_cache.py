import io
import os

from PIL import Image


def validate_and_clean_cache(cache_dir):
    if not os.path.exists(cache_dir):
        print(f"Cache directory {cache_dir} does not exist.")
        return

    deleted_count = 0
    scanned_count = 0

    for filename in os.listdir(cache_dir):
        if not filename.endswith(".img"):
            continue

        file_path = os.path.join(cache_dir, filename)
        meta_path = file_path + ".meta"

        scanned_count += 1
        is_corrupted = False

        try:
            with open(file_path, "rb") as f:
                data = f.read()

            if not data:
                is_corrupted = True
            else:
                try:
                    img = Image.open(io.BytesIO(data))
                    img.verify()
                    # verify() doesn't catch all truncation errors, so we also need to load it
                    img = Image.open(io.BytesIO(data))
                    img.load()
                except Exception:
                    # Verification failed
                    is_corrupted = True
        except Exception as e:
            print(f"Failed to read {filename}: {e}")
            is_corrupted = True

        if is_corrupted:
            print(f"Corrupted image detected, deleting: {filename}")
            try:
                os.remove(file_path)
                if os.path.exists(meta_path):
                    os.remove(meta_path)
                deleted_count += 1
            except Exception as e:
                print(f"Failed to delete {filename}: {e}")

    print(f"Scan complete. Scanned {scanned_count} files, deleted {deleted_count} corrupted files.")

if __name__ == "__main__":
    cache_dir = os.environ.get("COMFY_PREVIEW_CACHE_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "preview_cache"))
    validate_and_clean_cache(cache_dir)
