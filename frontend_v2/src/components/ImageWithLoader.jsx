import { useState, memo } from 'react';
import { Loader2, ImageIcon } from 'lucide-react';

/**
 * Image component with loading and error states
 * Provides smooth fade-in effect and loading indicators
 */
const ImageWithLoader = memo(function ImageWithLoader({ src, alt, className = '', onLoad, onError, ...props }) {
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState(false);

    const handleLoad = (e) => {
        setLoaded(true);
        if (onLoad) onLoad(e);
    };

    const handleError = (e) => {
        setError(true);
        if (onError) onError(e);
    };

    return (
        <div className="relative w-full h-full">
            {/* Loading State */}
            {!loaded && !error && (
                <div className="absolute inset-0 flex items-center justify-center bg-gray-800/50 backdrop-blur-sm">
                    <Loader2 className="animate-spin text-gray-600" size={24} />
                </div>
            )}

            {/* Error State */}
            {error && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-800 text-gray-500">
                    <ImageIcon size={32} className="mb-2 opacity-50" />
                    <span className="text-xs">Failed to load</span>
                </div>
            )}

            {/* Image */}
            <img
                src={src}
                alt={alt}
                className={`w-full h-full ${className} ${loaded ? 'opacity-100' : 'opacity-0'} transition-opacity duration-300`}
                onLoad={handleLoad}
                onError={handleError}
                loading="lazy"
                decoding="async"
                {...props}
            />
        </div>
    );
});

export default ImageWithLoader;
