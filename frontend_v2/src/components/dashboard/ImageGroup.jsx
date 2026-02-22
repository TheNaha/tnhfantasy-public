import { memo } from 'react';
import { Images } from 'lucide-react';

/**
 * ImageGroup component displays multiple images from a single job as a stacked effect.
 * Used when a job produces multiple output images.
 */
const ImageGroup = memo(function ImageGroup({
    images,
    job,
    onClick,
    onContextMenu,
    isSelected = false,
    showSelectionCheckbox = false,
    onSelectionToggle
}) {
    const count = images.length;
    const primaryImage = images[0];

    // Get thumbnail URL for an image
    const getThumbnail = (img) => {
        if (img.thumbnails?.medium) return img.thumbnails.medium;
        return `/api/thumbnail/medium/${encodeURIComponent(img.name)}`;
    };

    return (
        <div
            className={`relative aspect-square rounded-xl overflow-hidden cursor-pointer group
                ${isSelected ? 'ring-2 ring-purple-500' : 'hover:ring-2 hover:ring-gray-500'}`}
            onClick={() => onClick?.(primaryImage)}
            onContextMenu={onContextMenu}
        >
            {/* Stacked card effect - show up to 3 layers */}
            {count >= 3 && (
                <div className="absolute inset-0 bg-gray-700 rounded-xl transform rotate-3 translate-x-1 translate-y-1 opacity-60" />
            )}
            {count >= 2 && (
                <div className="absolute inset-0 bg-gray-600 rounded-xl transform rotate-1.5 translate-x-0.5 translate-y-0.5 opacity-80" />
            )}

            {/* Primary image */}
            <div className="absolute inset-0 rounded-xl overflow-hidden bg-gray-800">
                <img
                    src={getThumbnail(primaryImage)}
                    alt={primaryImage.name}
                    className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                    loading="lazy"
                />
            </div>

            {/* Count badge */}
            <div className="absolute bottom-2 right-2 bg-black/70 backdrop-blur-sm px-2 py-1 rounded-lg flex items-center gap-1.5 text-xs text-white font-medium">
                <Images size={12} />
                {count} images
            </div>



            {/* Selection checkbox */}
            {showSelectionCheckbox && (
                <div
                    className="absolute top-2 right-2 z-10"
                    onClick={(e) => {
                        e.stopPropagation();
                        onSelectionToggle?.();
                    }}
                >
                    <div className={`w-6 h-6 rounded-md border-2 flex items-center justify-center transition-colors
                        ${isSelected
                            ? 'bg-purple-500 border-purple-500'
                            : 'bg-black/50 border-white/50 hover:border-white'}`}
                    >
                        {isSelected && (
                            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                            </svg>
                        )}
                    </div>
                </div>
            )}

            {/* Hover overlay showing thumbnails grid preview */}
            <div className="absolute inset-0 bg-black/80 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center justify-center">
                <div className="grid grid-cols-2 gap-1 p-3 w-full h-full">
                    {images.slice(0, 4).map((img, i) => (
                        <div key={img.name} className="relative overflow-hidden rounded">
                            <img
                                src={getThumbnail(img)}
                                alt={img.name}
                                className="w-full h-full object-cover"
                                loading="lazy"
                            />
                            {i === 3 && count > 4 && (
                                <div className="absolute inset-0 bg-black/60 flex items-center justify-center text-white font-bold">
                                    +{count - 4}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
});

export default ImageGroup;
