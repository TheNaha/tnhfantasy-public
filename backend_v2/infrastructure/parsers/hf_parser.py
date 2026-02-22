# HuggingFace Model Metadata Parser and Normalizer
# Converts HuggingFace model data to CivitAI-compatible format for unified UI/UX

import re
import hashlib
from typing import Dict, List, Optional, Any


def infer_model_type(tags: List[str], pipeline_tag: str = None) -> str:
    """
    Infer ComfyUI model type from HuggingFace tags and pipeline.
    
    Returns: 'Checkpoint', 'LORA', 'TextualInversion', 'Controlnet', 'VAE', etc.
    """
    tags_lower = [t.lower() for t in tags]
    
    # Check for LoRA
    if 'lora' in tags_lower or 'locon' in tags_lower or 'dora' in tags_lower:
        return 'LORA'
    
    # Check for ControlNet
    if 'controlnet' in tags_lower or pipeline_tag == 'controlnet':
        return 'Controlnet'
    
    # Check for VAE
    if 'vae' in tags_lower:
        return 'VAE'
    
    # Check for TextualInversion/Embeddings
    if 'textual-inversion' in tags_lower or 'embedding' in tags_lower:
        return 'TextualInversion'
    
    # Check for Upscaler
    if 'upscaler' in tags_lower or 'real-esrgan' in tags_lower:
        return 'Upscaler'
    
    # Check for Hypernetwork
    if 'hypernetwork' in tags_lower:
        return 'Hypernetwork'
    
    # Check for Motion Modules (AnimateDiff)
    if 'motion' in tags_lower or 'animatediff' in tags_lower:
        return 'MotionModule'
    
    # Check for Poses
    if 'pose' in tags_lower or 'poses' in tags_lower:
        return 'Poses'
    
    # Default to Checkpoint for diffusion models
    if 'diffusers' in tags_lower or pipeline_tag in ['text-to-image', 'image-to-image']:
        return 'Checkpoint'
    
    return 'Checkpoint'  # Safe default


def infer_base_model(tags: List[str], card_content: str = None) -> str:
    """
    Infer base model version from tags and model card.
    
    Returns: 'SD 1.5', 'SDXL 1.0', 'SD 3', 'Pony', etc.
    """
    tags_lower = [t.lower() for t in tags]
    card_lower = (card_content or '').lower()
    
    # Check for SDXL
    if any('sdxl' in t for t in tags_lower) or 'sdxl' in card_lower:
        return 'SDXL 1.0'
    
    # Check for SD 3
    if any('sd3' in t or 'stable-diffusion-3' in t for t in tags_lower) or 'stable diffusion 3' in card_lower:
        return 'SD 3'
    
    # Check for Pony
    if any('pony' in t for t in tags_lower) or 'pony' in card_lower:
        return 'Pony'
    
    # Check for SD 2.x
    if any('sd2' in t or 'stable-diffusion-2' in t for t in tags_lower):
        return 'SD 2.1'
    
    # Check for SD 1.5 (most common)
    if any('sd15' in t or 'sd-1-5' in t or 'stable-diffusion-v1-5' in t for t in tags_lower):
        return 'SD 1.5'
    
    # Check in card content
    if 'stable diffusion 1.5' in card_lower or 'sd 1.5' in card_lower:
        return 'SD 1.5'
    
    # Default based on common patterns
    if 'stable-diffusion' in card_lower:
        return 'SD 1.5'  # Most common
    
    return 'SD 1.5'  # Safe default


def extract_preview_images(card_content: str) -> List[Dict[str, Any]]:
    """
    Extract image URLs from HuggingFace model card (README.md).
    
    Returns list of image dicts compatible with CivitAI format.
    """
    if not card_content:
        return []
    
    images = []
    
    # Match markdown images: ![alt](url)
    markdown_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    matches = re.findall(markdown_pattern, card_content)
    
    for alt_text, url in matches:
        # Skip badges and icons
        if any(skip in url.lower() for skip in ['badge', 'shield', 'button', 'icon']):
            continue
        
        # Make relative URLs absolute
        if url.startswith('/'):
            continue  # Skip relative URLs we can't resolve
        elif not url.startswith('http'):
            continue
        
        images.append({
            'url': url,
            'type': 'image',
            'width': None,
            'height': None,
            'meta': {'alt': alt_text} if alt_text else {}
        })
    
    # Also check for HTML img tags
    html_pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
    html_matches = re.findall(html_pattern, card_content)
    
    for url in html_matches:
        if any(skip in url.lower() for skip in ['badge', 'shield', 'button', 'icon']):
            continue
        
        if url.startswith('http'):
            images.append({
                'url': url,
                'type': 'image',
                'width': None,
                'height': None
            })
    
    return images[:10]  # Limit to first 10 images


def extract_description(card_content: str) -> str:
    """
    Extract a clean description from the model card.
    
    Returns first substantial paragraph or summary.
    """
    if not card_content:
        return "No description available."
    
    # Remove YAML frontmatter if present
    content = re.sub(r'^---\n.*?\n---\n', '', card_content, flags=re.DOTALL)
    
    # Remove markdown headers
    content = re.sub(r'^#+\s+', '', content, flags=re.MULTILINE)
    
    # Split into paragraphs
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    
    # Find first substantial paragraph (more than 50 chars, not a list item)
    for para in paragraphs:
        if len(para) > 50 and not para.startswith('-') and not para.startswith('*'):
            # Limit length
            if len(para) > 500:
                return para[:497] + '...'
            return para
    
    # Fallback
    if paragraphs:
        return paragraphs[0][:500]
    
    return "No description available."


def generate_hf_id(repo_id: str) -> int:
    """
    Generate a pseudo-unique integer ID from HuggingFace repo ID.
    Uses hash to create consistent ID for same repo.
    """
    # Create hash and convert to int
    hash_obj = hashlib.md5(repo_id.encode())
    # Take first 8 bytes and convert to int
    return int.from_bytes(hash_obj.digest()[:8], 'big') % (10**9)  # Keep it reasonable size


def normalize_hf_to_civitai(hf_data: Dict[str, Any], files_data: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Convert HuggingFace model data to CivitAI-compatible format.
    
    Args:
        hf_data: Response from HuggingFace models API
        files_data: Optional response from HuggingFace files API
    
    Returns:
        Dict in CivitAI format with modelVersions structure
    """
    repo_id = hf_data.get('id') or hf_data.get('modelId') or 'unknown'
    model_name = repo_id.split('/')[-1] if '/' in repo_id else repo_id
    author = hf_data.get('author', repo_id.split('/')[0] if '/' in repo_id else 'unknown')
    
    # Extract metadata
    tags = hf_data.get('tags', [])
    pipeline_tag = hf_data.get('pipeline_tag')
    card_content = hf_data.get('cardData', {}).get('content') or hf_data.get('card', '')
    
    # Infer model properties
    model_type = infer_model_type(tags, pipeline_tag)
    base_model = infer_base_model(tags, card_content)
    
    # Extract images and description
    images = extract_preview_images(card_content)
    description = extract_description(card_content)
    
    # Get file information
    download_url = f"https://huggingface.co/{repo_id}/resolve/main"
    
    # Try to find main model file
    main_file = None
    file_size_kb = 0
    
    if files_data:
        # Look for .safetensors or .ckpt files
        for file in files_data:
            path = file.get('path', '')
            if path.endswith('.safetensors') or path.endswith('.ckpt') or path.endswith('.pt'):
                main_file = path
                file_size_kb = file.get('size', 0) // 1024  # Convert bytes to KB
                break
    
    # Fallback filename based on model type
    if not main_file:
        if model_type == 'Checkpoint':
            main_file = 'model.safetensors'
        elif model_type == 'LORA':
            main_file = 'pytorch_lora_weights.safetensors'
        else:
            main_file = 'model.safetensors'
    
    # Build CivitAI-compatible structure
    normalized = {
        'id': generate_hf_id(repo_id),
        'name': model_name.replace('-', ' ').replace('_', ' ').title(),
        'description': description,
        'type': model_type,
        'nsfw': False,  # HuggingFace doesn't have NSFW flagging
        'tags': [t for t in tags if t not in ['diffusers', 'safetensors', 'pytorch']],  # Filter technical tags
        'creator': {
            'username': author,
            'image': None
        },
        'stats': {
            'downloadCount': hf_data.get('downloads', 0),
            'favoriteCount': hf_data.get('likes', 0),
            'thumbsUpCount': hf_data.get('likes', 0),
            'rating': 0,
            'ratingCount': 0
        },
        'modelVersions': [
            {
                'id': generate_hf_id(f"{repo_id}-main"),
                'name': 'main',
                'description': f"Main version from HuggingFace ({repo_id})",
                'baseModel': base_model,
                'createdAt': hf_data.get('createdAt', ''),
                'updatedAt': hf_data.get('lastModified', ''),
                'trainedWords': [],  # HF doesn't expose this easily
                'files': [
                    {
                        'id': generate_hf_id(f"{repo_id}-{main_file}"),
                        'name': main_file,
                        'sizeKB': file_size_kb or 2000000,  # Default 2GB if unknown
                        'type': 'Model',
                        'format': 'SafeTensor' if main_file.endswith('.safetensors') else 'PickleTensor',
                        'primary': True,
                        'downloadUrl': f"{download_url}/{main_file}"
                    }
                ],
                'images': images if images else [],
                'sha': hf_data.get('sha', '')
            }
        ],
        # Add source identifier
        '_source': 'huggingface',
        '_repo_id': repo_id
    }
    
    return normalized


def fetch_hf_files(repo_id: str) -> List[Dict[str, Any]]:
    """
    Fetch file tree from HuggingFace repo.
    
    Returns list of file objects with path and size.
    """
    import requests
    
    url = f"https://huggingface.co/api/models/{repo_id}/tree/main"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Warning: Could not fetch HF files for {repo_id}: {e}")
        return []


def parse_hf_url(url: str) -> Optional[Dict[str, str]]:
    """
    Parse a HuggingFace URL to extract repo_id, branch, and file path.
    
    Args:
        url: HuggingFace URL (e.g., https://huggingface.co/user/model/resolve/main/file.safetensors)
        
    Returns:
        Dict with 'repo_id', 'branch', 'file_path' or None if invalid
    """
    # Patterns for HuggingFace URLs
    patterns = [
        # Direct file resolve URL
        r'huggingface\.co/([^/]+/[^/]+)/resolve/([^/]+)/(.+)',
        # Blob URL
        r'huggingface\.co/([^/]+/[^/]+)/blob/([^/]+)/(.+)',
        # Simple repo URL
        r'huggingface\.co/([^/]+/[^/]+)/?$',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            groups = match.groups()
            if len(groups) == 3:
                return {
                    'repo_id': groups[0],
                    'branch': groups[1],
                    'file_path': groups[2]
                }
            elif len(groups) == 1:
                return {
                    'repo_id': groups[0],
                    'branch': 'main',
                    'file_path': None
                }
    
    return None


def get_download_url(repo_id: str, file_path: str, branch: str = 'main') -> str:
    """
    Generate a direct download URL for a HuggingFace file.
    
    Args:
        repo_id: The repository ID (e.g., 'user/model')
        file_path: Path to the file in the repo
        branch: Branch name (default: 'main')
        
    Returns:
        Direct download URL
    """
    return f"https://huggingface.co/{repo_id}/resolve/{branch}/{file_path}"
