import sys
from pprint import pprint

sys.path.append("/home/thenaha/containers/stacks/comfyui/backend_v2")
from core.workflow_builder import WorkflowBuilder, GeneratorOptions

def test_builder():
    opts = GeneratorOptions(
        prompt="A cute cat",
        checkpoint="model.safetensors",
        loras=[{"name": "cat.safetensors", "strength": 0.8}]
    )
    builder = WorkflowBuilder()
    wf = builder.build(opts)
    pprint(wf)

if __name__ == "__main__":
    test_builder()
