import modal
import os
import json

app = modal.App("debug-metadata")
vol = modal.Volume.from_name("comfy-storage")

@app.function(volumes={"/mnt/data": vol})
def check_metadata():
    target_dir = "/mnt/data/models/loras"
    print(f"Listing {target_dir}...")
    
    try:
        entries = os.listdir(target_dir)
        entries.sort()
        
        print(f"Found {len(entries)} files.")
        
        # Find pairs
        safetensors = [f for f in entries if f.endswith('.safetensors')]
        jsons = set([f for f in entries if f.endswith('.json')])
        
        print("\nChecking pairs:")
        for st in safetensors[:5]: # Check first 5
            base = os.path.splitext(st)[0]
            expected_json = f"{base}.json"
            
            print(f"Model: {st}")
            if expected_json in jsons:
                print(f"  -> Found JSON: {expected_json}")
                # Read content
                try:
                    with open(os.path.join(target_dir, expected_json), 'r') as f:
                        data = json.load(f)
                        print(f"  -> Content keys: {list(data.keys())}")
                except Exception as e:
                    print(f"  -> Error reading JSON: {e}")
            else:
                print(f"  -> MISSING JSON: {expected_json}")
                
    except Exception as e:
        print(f"Error: {e}")

@app.local_entrypoint()
def main():
    check_metadata.remote()
