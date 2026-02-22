import modal
import os

app = modal.App("debug-volume")
vol = modal.Volume.from_name("comfy-storage")

@app.function(volumes={"/mnt/data": vol})
def list_output():
    print("Listing /mnt/data:")
    try:
        print(os.listdir("/mnt/data"))
    except Exception as e:
        print(e)
        
    print("\nListing /mnt/data/output:")
    try:
        print(os.listdir("/mnt/data/output"))
    except Exception as e:
        print(e)

@app.local_entrypoint()
def main():
    list_output.remote()
