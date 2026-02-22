import { memo, useState } from 'react';
import { useLazyLoad } from '../hooks/useLazyLoad';

/**
 * LazyImage - Image component that only loads when visible in viewport.
 * Shows a placeholder until the image enters the viewport, then loads the actual image.
 * Includes fade-in animation when image loads.
 * 
 * @param {Object} props
 * @param {string} props.src - Image source URL
 * @param {string} props.alt - Image alt text
 * @param {string} props.className - Additional CSS classes
 * @param {string} props.placeholderColor - Background color for placeholder (default: bg-gray-800)
 * @param {React.ReactNode} props.placeholder - Custom placeholder content
 * @param {string} props.rootMargin - IntersectionObserver margin (default: '100px')
 * @param {function} props.onLoad - Callback when image loads
 * @param {function} props.onError - Callback on image error
 */
const LazyImage = memo(function LazyImage({
    src,
    alt = '',
    className = '',
    placeholderColor = 'bg-gray-800',
    placeholder,
    rootMargin = '100px',
    onLoad,
    onError,
    ...props
}) {
    const [ref, isVisible] = useLazyLoad({ rootMargin });
    const [isLoaded, setIsLoaded] = useState(false);
    const [hasError, setHasError] = useState(false);

    const handleLoad = (e) => {
        setIsLoaded(true);
        onLoad?.(e);
    };

    const handleError = (e) => {
        setHasError(true);
        onError?.(e);
    };

    return (
        <div
            ref={ref}
            className={`relative overflow-hidden ${placeholderColor} ${className}`}
            {...props}
        >
            {/* Placeholder - shown until image loads */}
            {(!isVisible || !isLoaded) && !hasError && (
                <div className="absolute inset-0 flex items-center justify-center">
                    {placeholder || (
                        <div className="w-8 h-8 rounded-full border-2 border-gray-600 border-t-gray-400 animate-spin" />
                    )}
                </div>
            )}

            {/* Error state */}
            {hasError && (
                <div className="absolute inset-0 flex items-center justify-center text-gray-500">
                    <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                </div>
            )}

            {/* Actual image - only loads when visible */}
            {isVisible && !hasError && (
                <img
                    src={src}
                    alt={alt}
                    className={`w-full h-full object-cover transition-opacity duration-300 ${isLoaded ? 'opacity-100' : 'opacity-0'
                        }`}
                    onLoad={handleLoad}
                    onError={handleError}
                />
            )}
        </div>
    );
});

export default LazyImage;
