/**
 * Skeleton loading component for better perceived performance
 * Enhanced with shimmer effect for modern UX
 */

// Shimmer overlay component - reusable shimmer animation
function Shimmer() {
    return (
        <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/10 to-transparent animate-shimmer" />
    );
}

// Base skeleton with shimmer
function SkeletonBase({ className = "", children }) {
    return (
        <div className={`relative overflow-hidden bg-gray-800 ${className}`}>
            {children}
            <Shimmer />
        </div>
    );
}

export function ImageSkeleton({ className = "", aspectRatio = "square" }) {
    const aspectClass = aspectRatio === "square" ? "aspect-square" :
        aspectRatio === "video" ? "aspect-video" :
            aspectRatio === "portrait" ? "aspect-[2/3]" : "";
    return (
        <SkeletonBase className={`rounded-xl ${className}`}>
            <div className={`${aspectClass} w-full bg-gradient-to-br from-gray-800 via-gray-750 to-gray-900`} />
        </SkeletonBase>
    );
}

export function CardSkeleton({ className = "" }) {
    return (
        <SkeletonBase className={`rounded-2xl border border-gray-700/50 ${className}`}>
            {/* Header */}
            <div className="p-4 border-b border-gray-700/50 flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-gray-700" />
                <div className="flex-1 space-y-2">
                    <div className="h-3 bg-gray-700 rounded-full w-2/3" />
                    <div className="h-2 bg-gray-700/70 rounded-full w-1/3" />
                </div>
            </div>
            {/* Image area */}
            <div className="aspect-[4/3] bg-gradient-to-br from-gray-800 to-gray-900" />
            {/* Footer */}
            <div className="p-4 space-y-3">
                <div className="h-3 bg-gray-700 rounded-full w-full" />
                <div className="h-3 bg-gray-700/70 rounded-full w-2/3" />
            </div>
        </SkeletonBase>
    );
}

export function GallerySkeleton({ count = 8, mode = "grid" }) {
    if (mode === "grid") {
        return (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                {Array.from({ length: count }).map((_, i) => (
                    <ImageSkeleton key={i} aspectRatio="square" />
                ))}
            </div>
        );
    }

    if (mode === "list") {
        return (
            <div className="space-y-2">
                {Array.from({ length: count }).map((_, i) => (
                    <SkeletonBase key={i} className="flex items-center gap-4 p-3 rounded-xl border border-gray-700/50">
                        <div className="w-16 h-16 bg-gray-700 rounded-lg flex-shrink-0" />
                        <div className="flex-1 space-y-2">
                            <div className="h-3 bg-gray-700 rounded-full w-3/4" />
                            <div className="h-2 bg-gray-700/70 rounded-full w-1/2" />
                        </div>
                        <div className="flex gap-2">
                            <div className="w-8 h-8 bg-gray-700 rounded-lg" />
                            <div className="w-8 h-8 bg-gray-700 rounded-lg" />
                        </div>
                    </SkeletonBase>
                ))}
            </div>
        );
    }

    // Feed mode - uses FeedCardSkeleton for accurate layout matching
    return (
        <div className="space-y-4 md:space-y-6 max-w-3xl mx-auto">
            {Array.from({ length: count }).map((_, i) => (
                <FeedCardSkeleton key={i} />
            ))}
        </div>
    );
}

// Feed card skeleton - matches FeedCard.jsx layout exactly
export function FeedCardSkeleton() {
    return (
        <SkeletonBase className="rounded-2xl border border-gray-700/50 overflow-hidden">
            {/* Header - matches FeedCard header */}
            <div className="p-4 border-b border-gray-700/50 flex items-center justify-between bg-gray-900/50">
                <div className="flex items-center gap-3 flex-1 min-w-0">
                    {/* Avatar */}
                    <div className="w-8 h-8 rounded-full bg-gray-700 flex-shrink-0" />
                    {/* Model name and timestamp */}
                    <div className="min-w-0 flex-1 space-y-1.5">
                        <div className="h-3.5 bg-gray-700 rounded-full w-32" />
                        <div className="h-2.5 bg-gray-700/60 rounded-full w-24" />
                    </div>
                </div>
                {/* Action buttons */}
                <div className="flex gap-2 flex-shrink-0">
                    <div className="w-9 h-9 bg-gray-700 rounded-lg" />
                    <div className="w-9 h-9 bg-gray-700 rounded-lg hidden md:block" />
                    <div className="w-9 h-9 bg-gray-700 rounded-lg" />
                    <div className="w-9 h-9 bg-gray-700 rounded-lg" />
                </div>
            </div>
            {/* Image area - auto aspect ratio like FeedCard */}
            <div className="aspect-square bg-gradient-to-br from-gray-800 via-gray-750 to-gray-900" />
        </SkeletonBase>
    );
}

export function ModelCardSkeleton() {
    return (
        <SkeletonBase className="rounded-xl border border-gray-700/50">
            {/* Image */}
            <div className="aspect-[2/3] bg-gradient-to-br from-gray-800 via-gray-750 to-gray-900" />
            {/* Content */}
            <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-black/90 via-black/50 to-transparent">
                <div className="h-4 bg-gray-700/80 rounded-full w-3/4 mb-2" />
                <div className="h-3 bg-gray-700/60 rounded-full w-1/2" />
            </div>
        </SkeletonBase>
    );
}

export function TextSkeleton({ lines = 3, className = "" }) {
    return (
        <SkeletonBase className={`space-y-2 p-1 rounded ${className}`}>
            {Array.from({ length: lines }).map((_, i) => (
                <div
                    key={i}
                    className="h-3 bg-gray-700 rounded-full"
                    style={{ width: i === lines - 1 ? '60%' : i % 2 === 0 ? '100%' : '85%' }}
                />
            ))}
        </SkeletonBase>
    );
}

// Stats skeleton for dashboard header
export function StatsSkeleton() {
    return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
                <SkeletonBase key={i} className="p-4 rounded-xl border border-gray-700/50">
                    <div className="h-3 bg-gray-700 rounded-full w-1/2 mb-3" />
                    <div className="h-6 bg-gray-700 rounded-full w-2/3" />
                </SkeletonBase>
            ))}
        </div>
    );
}

// Table skeleton for data grids
export function TableSkeleton({ rows = 5, cols = 4 }) {
    return (
        <SkeletonBase className="rounded-xl border border-gray-700/50 overflow-hidden">
            {/* Header */}
            <div className="grid gap-4 p-4 border-b border-gray-700/50 bg-gray-800/50"
                style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
                {Array.from({ length: cols }).map((_, i) => (
                    <div key={i} className="h-3 bg-gray-700 rounded-full" />
                ))}
            </div>
            {/* Rows */}
            {Array.from({ length: rows }).map((_, rowIdx) => (
                <div key={rowIdx}
                    className="grid gap-4 p-4 border-b border-gray-700/30"
                    style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
                    {Array.from({ length: cols }).map((_, colIdx) => (
                        <div key={colIdx} className="h-3 bg-gray-700/70 rounded-full"
                            style={{ width: colIdx === 0 ? '80%' : '60%' }} />
                    ))}
                </div>
            ))}
        </SkeletonBase>
    );
}
