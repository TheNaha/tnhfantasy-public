import { memo } from 'react';
import { Image as ImageIcon } from 'lucide-react';
import ProgressiveImage from '../ProgressiveImage';
import { getOptimizedImageUrl } from '../../utils/imageOptimization';

function ModelPreviewImage({ model, size = 'md', className = '' }) {
  const sizeClass = size === 'sm'
    ? 'w-10 h-10 rounded'
    : 'absolute inset-0 w-full h-full object-cover';

  const placeholderSize = size === 'sm'
    ? 'w-10 h-10 rounded'
    : 'absolute inset-0';

  const previewWidth = size === 'sm' ? 150 : 450;

  if (model?.preview) {
    return (
      <ProgressiveImage
        src={model.preview}
        medium={getOptimizedImageUrl(model.preview, previewWidth)}
        alt={model?.display_name || model?.name}
        className={`${sizeClass} bg-gray-800 flex-shrink-0 ${size === 'lg' ? 'transition-transform group-hover:scale-105' : ''} ${className}`}
        size="medium"
        aspectRatio={size === 'sm' ? '1/1' : 'auto'}
        onError={(e) => {
          if (model?.civitai_id) {
            const versionPreviewId = model.selectedVersionPreviewId || model.selectedVersionId;
            const params = new URLSearchParams({ image_index: '0' });
            if (versionPreviewId) {
              params.set('version_id', String(versionPreviewId));
            }
            const proxyPreview = `/api/v2/models/preview/${model.civitai_id}?${params.toString()}`;
            if (e.currentTarget.src !== proxyPreview) {
              e.currentTarget.src = proxyPreview;
              return;
            }
          }
          e.target.style.display = 'none';
        }}
      />
    );
  }

  if (model?.civitai_id) {
    const versionPreviewId = model.selectedVersionPreviewId || model.selectedVersionId;
    const params = new URLSearchParams({ image_index: '0' });
    if (versionPreviewId) {
      params.set('version_id', String(versionPreviewId));
    }
    return (
      <ProgressiveImage
        src={`/api/v2/models/preview/${model.civitai_id}?${params.toString()}`}
        alt={model?.display_name || model?.name}
        className={`${sizeClass} bg-gray-800 flex-shrink-0 ${size === 'lg' ? 'transition-transform group-hover:scale-105' : ''} ${className}`}
        size="medium"
        aspectRatio={size === 'sm' ? '1/1' : 'auto'}
        onError={(e) => {
          e.target.style.display = 'none';
        }}
      />
    );
  }

  if (size === 'sm') {
    return (
      <div className={`${placeholderSize} bg-gray-800 flex items-center justify-center text-gray-600 group-hover:text-gray-400 flex-shrink-0 ${className}`}>
        <ImageIcon size={20} />
      </div>
    );
  }

  return (
    <div className={`${placeholderSize} bg-gray-800 flex flex-col items-center justify-center text-gray-600 p-4 ${className}`}>
      <ImageIcon size={32} className="mb-2 opacity-50" />
      <span className="text-xs text-center break-all opacity-50">
        {model.display_name || model.name}
      </span>
    </div>
  );
}

export default memo(ModelPreviewImage);
