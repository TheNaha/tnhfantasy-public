import modal
import os
import json
import logging
from typing import List, Dict, Any

# Configure logging for Modal functions
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger("modal_app_vllm")

app = modal.App(os.getenv("MODAL_APP_NAME", "vllm-modal-stack"))
vol = modal.Volume.from_name(os.getenv("MODAL_VOLUME_NAME", "comfy-llm-models"), create_if_missing=True)

# Define the image with vLLM
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("vllm", "fastapi", "uvicorn", "huggingface_hub", "hf-transfer")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

@app.cls(image=image, gpu="A100", volumes={"/mnt/data": vol}, timeout=3600)
class VLLMEngine:
    @modal.enter()
    def setup(self):
        # In a real scenario, this might initialize an AsyncLLMEngine.
        # However, vLLM AsyncLLMEngine requires a model at initialization.
        # We will initialize it lazily in generate() or just wrap the OpenAI API Server if needed.
        self.engine = None
        self.current_model = None
        
    @modal.method()
    async def generate(self, model_id: str, messages: List[Dict[str, str]]):
        import json
        from vllm import AsyncLLMEngine, AsyncEngineArgs
        from vllm.sampling_params import SamplingParams
        import uuid
        
        model_path = f"/mnt/data/{model_id}"
        
        # Lazy load engine if model changed
        if self.current_model != model_path:
            if self.engine is not None:
                # Cleanup old engine if possible
                pass
            engine_args = AsyncEngineArgs(model=model_path, tensor_parallel_size=1)
            self.engine = AsyncLLMEngine.from_engine_args(engine_args)
            self.current_model = model_path
            
        prompt = ""
        for m in messages:
            prompt += f"{m['role'].capitalize()}: {m['content']}\n"
        prompt += "Assistant: "

        sampling_params = SamplingParams(temperature=0.8, top_p=0.95, max_tokens=1024)
        request_id = str(uuid.uuid4())
        
        async for request_output in self.engine.generate(prompt, sampling_params, request_id):
            if request_output.finished:
                output_text = request_output.outputs[0].text
                yield json.dumps({
                    "type": "completed",
                    "outputs": [{"role": "assistant", "content": output_text}]
                })
            else:
                yield json.dumps({
                    "type": "progress",
                    "progress": 0,
                    "message": request_output.outputs[0].text
                })

# File Management Functions
@app.function(image=image, volumes={"/mnt/data": vol})
def download_model(url: str, path: str, token: str = None):
    import urllib.request
    full_path = f"/mnt/data/{path}"
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
        
    with urllib.request.urlopen(req) as response, open(full_path, 'wb') as out_file:
        data = response.read()
        out_file.write(data)
    
    vol.commit()
    return {"status": "success"}

@app.function(image=image, volumes={"/mnt/data": vol})
def list_models(directory: str):
    import os
    full_dir = f"/mnt/data/{directory}"
    if not os.path.exists(full_dir):
        return []
    
    files = []
    for root, _, filenames in os.walk(full_dir):
        for filename in filenames:
            rel_path = os.path.relpath(os.path.join(root, filename), full_dir)
            files.append({"name": filename, "path": f"{directory}/{rel_path}"})
            
    return files

@app.function(image=image, volumes={"/mnt/data": vol})
def delete_file(path: str):
    import os
    full_path = f"/mnt/data/{path}"
    if os.path.exists(full_path):
        os.remove(full_path)
        vol.commit()
        return True
    return False
