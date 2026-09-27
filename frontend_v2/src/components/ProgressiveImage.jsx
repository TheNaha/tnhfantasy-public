import { useState, useEffect, useRef, memo } from 'react';
import { Blurhash } from 'react-blurhash';
import { observeIntersection, unobserveIntersection } from '../utils/sharedObserver';

/**
 * ProgressiveImage - Loads images progressively with BlurHash placeholder
 * 
 * Features:
 * - Instant BlurHash placeholder
 * - Lazy loading with shared Intersection Observer (for thumbnails)
 * - Immediate loading for full-size images (lightbox/modal)
 * - Smooth fade-in transition
 * - Support for different sizes (medium/full)
 */
const ProgressiveImage = memo(function ProgressiveImage({
    blurhash,
    src,
    medium,
    alt = '',
    className = '',
    size = 'full', // 'medium' or 'full'
    aspectRatio = '1 / 1',
    objectFit = null,
    onLoad,
    onError,
}) {
    // Which src has finished loading, not a bare boolean: the lightbox reuses
    // this component across prev/next, so a `true` from the previous image
    // would skip both the blurhash and the opacity-0 placeholder and pop the
    // next one in fully loaded.
    const [loadedSrc, setLoadedSrc] = useState(null);
    const shouldLoadImmediately = size === 'full';
    // Initialize with shouldLoadImmediately to avoid effect update on mount if true
    const [hasBeenInView, setHasBeenInView] = useState(shouldLoadImmediately);
    const isInView = shouldLoadImmediately || hasBeenInView;

    const imgRef = useRef(null);
    const containerRef = useRef(null);

    // Determine which image to load based on size
    const imageSrc = size === 'medium' ? (medium || src) : src;
    const isLoaded = loadedSrc === imageSrc;

    // Intersection Observer for lazy loading (only for thumbnails/medium size)
    useEffect(() => {
        // If already in view or should load immediately, skip the observer
        if (isInView) {
            return;
        }

        const currentContainer = containerRef.current;
        if (!currentContainer) return;

        observeIntersection(currentContainer, () => {
            setHasBeenInView(true);
        });

        return () => unobserveIntersection(currentContainer);
    }, [isInView]);


    // Handle image load
    const handleLoad = () => {
        setLoadedSrc(imageSrc);
        if (onLoad) onLoad();
    };

    const isCover = objectFit === 'cover' || aspectRatio !== 'auto';

    return (
        <div
            ref={containerRef}
            className={`relative overflow-hidden ${className}`}
            style={aspectRatio !== 'auto' ? { aspectRatio } : {}}
        >
            {/* BlurHash Placeholder */}
            {blurhash && !isLoaded && (
                <Blurhash
                    hash={blurhash}
                    width="100%"
                    height="100%"
                    resolutionX={32}
                    resolutionY={32}
                    punch={1}
                    className={isCover ? 'absolute inset-0' : 'w-full h-auto'}
                />
            )}

            {/* Actual Image - only load when in view */}
            {isInView && (
                <img
                    ref={imgRef}
                    src={imageSrc}
                    alt={alt}
                    onLoad={handleLoad}
                    onError={onError}
                    className={`
                        transition-opacity duration-500
                        ${isLoaded ? 'opacity-100' : 'opacity-0'}
                        ${isCover ? 'absolute inset-0 w-full h-full object-cover' : 'max-w-full max-h-full object-contain'}
                    `}
                    loading="lazy"
                />
            )}

            {/* Fallback for no blurhash */}
            {!blurhash && !isLoaded && (
                <div className={aspectRatio !== 'auto' ? 'absolute inset-0 bg-gray-800 animate-pulse' : 'w-full h-32 bg-gray-800 animate-pulse'} />
            )}
        </div>
    );
});

export default ProgressiveImage;
