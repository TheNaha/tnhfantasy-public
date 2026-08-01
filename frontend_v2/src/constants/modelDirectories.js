export const PROVIDER_MODEL_DIRECTORIES = [
    'models/checkpoints',
    'models/loras',
    'models/vae',
    'models/controlnet',
    'models/unet',
    'models/clip',
    'models/upscale_models',
    'models/embeddings',
    'models/hypernetworks',
    'models/aesthetics',
    'models/poses',
    'models/wildcards',
    'models/ultralytics/bbox',
    'models/motion_modules',
    'models/llm',
];

export const GENERATOR_MODEL_REQUESTS = [
    { key: 'checkpoints', directory: 'models/checkpoints', label: 'checkpoints' },
    { key: 'controlNetModels', directory: 'models/controlnet', label: 'controlnet models' },
    { key: 'upscalerModels', directory: 'models/upscale_models', label: 'upscaler models' },
    { key: 'adetailerModels', directory: 'models/ultralytics/bbox', label: 'adetailer models' },
    { key: 'vaeModels', directory: 'models/vae', label: 'VAE models' },
    { key: 'clipModels', directory: 'models/clip', label: 'CLIP models' },
    { key: 'unetModels', directory: 'models/unet', label: 'UNET models' },
    { key: 'embeddingModels', directory: 'models/embeddings', label: 'embedding models' },
];

export const BASIC_GENERATOR_MODEL_REQUESTS = [
    { key: 'checkpoints', directory: 'models/checkpoints', label: 'checkpoints' },
    { key: 'vaeModels', directory: 'models/vae', label: 'VAE models' },
];

export const MODEL_MANAGER_CATEGORIES = [
    { id: 'checkpoints', label: 'Checkpoints', path: 'models/checkpoints' },
    { id: 'unet', label: 'UNET (Flux)', path: 'models/unet' },
    { id: 'loras', label: 'LoRAs', path: 'models/loras' },
    { id: 'controlnet', label: 'ControlNet', path: 'models/controlnet' },
    { id: 'embeddings', label: 'Embeddings', path: 'models/embeddings' },
    { id: 'vae', label: 'VAE', path: 'models/vae' },
    { id: 'clip', label: 'CLIP', path: 'models/clip' },
    { id: 'hypernetworks', label: 'Hypernetworks', path: 'models/hypernetworks' },
    { id: 'aesthetics', label: 'Aesthetics', path: 'models/aesthetics' },
    { id: 'poses', label: 'Poses', path: 'models/poses' },
    { id: 'wildcards', label: 'Wildcards', path: 'models/wildcards' },
    { id: 'adetailer', label: 'ADetailer', path: 'models/ultralytics/bbox' },
    { id: 'motion_modules', label: 'Motion', path: 'models/motion_modules' },
    { id: 'llm', label: 'LLM', path: 'models/llm' },
];
