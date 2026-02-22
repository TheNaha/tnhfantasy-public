import { useState, useEffect, useRef } from 'react';
import { Blurhash } from 'react-blurhash';

/**
 * ProgressiveImage - Loads images progressively with BlurHash placeholder
 * 
 * Features:
 * - Instant BlurHash placeholder
 * - Lazy loading with Intersection Observer (for thumbnails)
 * - Immediate loading for full-size images (lightbox/modal)
 * - Smooth fade-in transition
 * - Support for different sizes (medium/full)
 */
export default function ProgressiveImage({
    blurhash,
    src,
    medium,
    alt = '',
    className = '',
    size = 'full', // 'medium' or 'full'
    aspectRatio = '1 / 1',
    onLoad,
}) {
    const [isLoaded, setIsLoaded] = useState(false);
    const [isInView, setIsInView] = useState(false);
    const imgRef = useRef(null);
    const containerRef = useRef(null);

    // Determine which image to load based on size
    const imageSrc = size === 'medium' ? (medium || src) : src;

    // For full-size images (lightbox), load immediately without waiting for IntersectionObserver
    // This fixes the issue where lightbox images appear blank
    const shouldLoadImmediately = size === 'full';

    // Intersection Observer for lazy loading (only for thumbnails/medium size)
    useEffect(() => {
        // If should load immediately, skip the observer
        if (shouldLoadImmediately) {
            setIsInView(true);
            return;
        }

        if (!containerRef.current) return;

        const observer = new IntersectionObserver(
            ([entry]) => {
                if (entry.isIntersecting) {
                    setIsInView(true);
                    observer.disconnect();
                }
            },
            {
                rootMargin: '200px', // Start loading 200px before entering viewport
            }
        );

        observer.observe(containerRef.current);

        return () => observer.disconnect();
    }, [shouldLoadImmediately]);


    // Handle image load
    const handleLoad = () => {
        setIsLoaded(true);
        if (onLoad) onLoad();
    };

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
                    className={aspectRatio !== 'auto' ? 'absolute inset-0' : 'w-full h-auto'}
                />
            )}

            {/* Actual Image - only load when in view */}
            {isInView && (
                <img
                    ref={imgRef}
                    src={imageSrc}
                    alt={alt}
                    onLoad={handleLoad}
                    className={`
                        transition-opacity duration-500
                        ${isLoaded ? 'opacity-100' : 'opacity-0'}
                        ${aspectRatio !== 'auto' ? 'absolute inset-0 w-full h-full object-cover' : 'w-full h-auto object-contain'}
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
}
