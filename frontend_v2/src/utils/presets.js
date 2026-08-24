export const PRESET_WORKFLOWS = {
  clear: {
    name: 'Clear Workflow',
    nodes: [],
    edges: []
  },
  sdxl_standard: {
    name: 'Standard SDXL Generator',
    nodes: [
      {
        id: 'node_checkpoint',
        type: 'comfy',
        position: { x: 100, y: 100 },
        data: { nodeType: 'CheckpointLoaderSimple', widgets: {} }
      },
      {
        id: 'node_prompt_pos',
        type: 'comfy',
        position: { x: 100, y: 350 },
        data: { nodeType: 'CLIPTextEncode', widgets: { text: '' } }
      },
      {
        id: 'node_prompt_neg',
        type: 'comfy',
        position: { x: 100, y: 550 },
        data: { nodeType: 'CLIPTextEncode', widgets: { text: '' } }
      },
      {
        id: 'node_empty_latent',
        type: 'comfy',
        position: { x: 100, y: 750 },
        data: { nodeType: 'EmptyLatentImage', widgets: { width: 1024, height: 1024, batch_size: 1 } }
      },
      {
        id: 'node_sampler',
        type: 'comfy',
        position: { x: 500, y: 300 },
        data: { nodeType: 'KSampler', widgets: { seed: 0, steps: 20, cfg: 7.0, sampler_name: 'euler', scheduler: 'normal', denoise: 1.0 } }
      },
      {
        id: 'node_decode',
        type: 'comfy',
        position: { x: 900, y: 300 },
        data: { nodeType: 'VAEDecode', widgets: {} }
      },
      {
        id: 'node_save',
        type: 'comfy',
        position: { x: 1200, y: 300 },
        data: { nodeType: 'SaveImage', widgets: { filename_prefix: 'ComfyUI' } }
      }
    ],
    edges: [
      { id: 'e1', source: 'node_checkpoint', sourceHandle: '0', target: 'node_sampler', targetHandle: 'model' },
      { id: 'e2', source: 'node_checkpoint', sourceHandle: '1', target: 'node_prompt_pos', targetHandle: 'clip' },
      { id: 'e3', source: 'node_checkpoint', sourceHandle: '1', target: 'node_prompt_neg', targetHandle: 'clip' },
      { id: 'e4', source: 'node_checkpoint', sourceHandle: '2', target: 'node_decode', targetHandle: 'vae' },
      { id: 'e5', source: 'node_prompt_pos', sourceHandle: '0', target: 'node_sampler', targetHandle: 'positive' },
      { id: 'e6', source: 'node_prompt_neg', sourceHandle: '0', target: 'node_sampler', targetHandle: 'negative' },
      { id: 'e7', source: 'node_empty_latent', sourceHandle: '0', target: 'node_sampler', targetHandle: 'latent_image' },
      { id: 'e8', source: 'node_sampler', sourceHandle: '0', target: 'node_decode', targetHandle: 'samples' },
      { id: 'e9', source: 'node_decode', sourceHandle: '0', target: 'node_save', targetHandle: 'images' }
    ]
  }
};
