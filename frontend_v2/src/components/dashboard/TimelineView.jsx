import { useMemo, memo } from 'react';
import { Calendar, Clock, Image as ImageIcon, Sparkles } from 'lucide-react';
import { motion as Motion, AnimatePresence } from 'framer-motion';
import ProgressiveImage from '../ProgressiveImage';
import JobCard from './JobCard';
import { getItemTimelineDate } from '../../utils/dateTime';
import { getCheckpointDisplayName } from '../../utils/modelDisplay';
import { assetUrl, assetPath } from '../../utils/assetUrl';
import { useWindowVirtualizer } from '@tanstack/react-virtual';

/**
 * TimelineView Component
 * Displays generation history in a chronological timeline format
 * Groups items by date with visual timeline connectors
 */
export const TimelineView = memo(function TimelineView({
    items = [],
    sort = 'date_desc',
    onImageClick,
    onJobClick,
    selectionMode = false,
    selectedFiles = new Set(),
    onToggleSelection,
    isFavorite,
    onToggleFavorite
}) {
    // Group items by date with enhanced metadata
    const timelineGroups = useMemo(() => {
        if (sort?.startsWith('random')) {
            const stats = items.reduce((acc, item) => {
                if (item.type === 'image') acc.totalImages++;
                else if (item.type === 'job') {
                    acc.totalJobs++;
                    if (item.status === 'success') acc.successful++;
                }
                return acc;
            }, { totalImages: 0, totalJobs: 0, successful: 0 });
            
            return [{
                date: 'Random Order',
                timestamp: Date.now(),
                items: items,
                stats
            }];
        }

        const groups = items.reduce((acc, item) => {
            const date = getItemTimelineDate(item);
            const dateKey = date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            });

            if (!acc[dateKey]) {
                acc[dateKey] = {
                    date: dateKey,
                    timestamp: date.getTime(),
                    items: [],
                    stats: {
                        totalImages: 0,
                        totalJobs: 0,
                        successful: 0
                    }
                };
            }

            acc[dateKey].items.push(item);

            // ⚡ Bolt: Pre-compute stats during the initial O(N) grouping pass
            // rather than calling .filter() three times per group on every render
            if (item.type === 'image') {
                acc[dateKey].stats.totalImages++;
            } else if (item.type === 'job') {
                acc[dateKey].stats.totalJobs++;
                if (item.status === 'success') {
                    acc[dateKey].stats.successful++;
                }
            }

            return acc;
        }, {});

        // Convert to array and sort by date (newest first)
        return Object.values(groups).sort((a, b) => b.timestamp - a.timestamp);
    }, [items, sort]);

    const virtualizer = useWindowVirtualizer({
        count: timelineGroups.length,
        estimateSize: (index) => {
            const itemCount = timelineGroups[index]?.items.length || 1;
            return Math.max(320, Math.min(2200, 180 + itemCount * 190));
        },
        getItemKey: (index) => timelineGroups[index]?.date || `timeline-${index}`,
        overscan: 2,
    });

    if (timelineGroups.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center py-20 text-gray-500">
                <Calendar size={64} className="mb-4 opacity-50" />
                <p className="text-lg">No items in timeline</p>
            </div>
        );
    }

    return (
        <div className="relative">
            {/* Timeline Line */}
            <div className="absolute left-8 top-0 bottom-0 w-0.5 bg-gradient-to-b from-blue-500 via-purple-500 to-transparent hidden md:block" />

            <div style={{ height: `${virtualizer.getTotalSize()}px`, position: 'relative', width: '100%', overflow: 'hidden' }}>
                {virtualizer.getVirtualItems().map((virtualItem) => {
                    const group = timelineGroups[virtualItem.index];
                    const stats = group.stats;

                    return (
                        <div
                            key={virtualItem.key}
                            data-index={virtualItem.index}
                            ref={virtualizer.measureElement}
                            style={{
                                position: 'absolute',
                                top: 0,
                                left: 0,
                                width: '100%',
                                transform: `translateY(${virtualItem.start}px)`,
                                paddingBottom: '3rem'
                            }}
                        >
                            <Motion.div
                                initial={{ opacity: 0, x: -20 }}
                                animate={{ opacity: 1, x: 0 }}
                                transition={{ delay: 0 }}
                                className="relative"
                            >
                                {/* Date Header */}
                                <div className="flex items-center gap-4 mb-6 md:pl-20">
                                {/* Timeline Dot */}
                                <div className="absolute left-6 w-4 h-4 bg-gradient-to-br from-blue-500 to-purple-500 rounded-full border-4 border-gray-900 shadow-lg hidden md:block" />

                                <div className="flex-1 flex items-center justify-between flex-wrap gap-4 bg-gray-800/50 backdrop-blur-sm border border-gray-700 rounded-lg p-4">
                                    <div className="flex items-center gap-3">
                                        <Calendar size={20} className="text-blue-400" />
                                        <div>
                                            <h3 className="text-lg font-semibold text-gray-200">
                                                {group.date}
                                            </h3>
                                            <p className="text-sm text-gray-500">
                                                {stats.totalImages} {stats.totalImages === 1 ? 'image' : 'images'}
                                                {stats.totalJobs > 0 && `, ${stats.totalJobs} ${stats.totalJobs === 1 ? 'job' : 'jobs'}`}
                                            </p>
                                        </div>
                                    </div>

                                    {stats.totalImages > 0 && (
                                        <div className="flex items-center gap-2 text-sm">
                                            <Sparkles size={16} className="text-purple-400" />
                                            <span className="text-gray-400">
                                                {stats.totalImages} generation{stats.totalImages !== 1 ? 's' : ''}
                                            </span>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* Timeline Items */}
                            <div className="md:pl-20 space-y-4">
                                <AnimatePresence mode="popLayout">
                                    {group.items.map((item, itemIndex) => (
                                        <Motion.div
                                            key={item.id || item.name}
                                            layout
                                            initial={{ opacity: 0, y: 20 }}
                                            animate={{ opacity: 1, y: 0 }}
                                            exit={{ opacity: 0, scale: 0.95 }}
                                            transition={{
                                                delay: itemIndex * 0.02,
                                                layout: { duration: 0.3 }
                                            }}
                                            className="relative"
                                        >
                                            {item.type === 'job' ? (
                                                <JobCard
                                                    job={item}
                                                    onClick={onJobClick} // ⚡ Bolt: Pass stable reference instead of () => onJobClick?.(item) to preserve JobCard's React.memo
                                                />
                                            ) : (
                                                <TimelineImageCard
                                                    item={item}
                                                    onImageClick={onImageClick}
                                                    onToggleSelection={onToggleSelection}
                                                    selectionMode={selectionMode}
                                                    isSelected={selectedFiles.has(item.name)}
                                                    isFavorite={isFavorite?.(item.name)}
                                                    onToggleFavorite={onToggleFavorite}
                                                />
                                            )}
                                        </Motion.div>
                                    ))}
                                </AnimatePresence>
                            </div>
                            </Motion.div>
                        </div>
                    );
                })}
            </div>

            {/* End of Timeline Marker */}
            <Motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.5 }}
                className="flex items-center gap-4 mt-12 md:pl-20"
            >
                <div className="absolute left-6 w-4 h-4 bg-gray-700 rounded-full border-4 border-gray-900 hidden md:block" />
                <div className="flex-1 text-center py-8 text-gray-600">
                    <Clock size={32} className="mx-auto mb-2 opacity-50" />
                    <p className="text-sm">End of timeline</p>
                </div>
            </Motion.div>
        </div>
    );
});

/**
 * TimelineImageCard - Individual image card for timeline view
 */
const TimelineImageCard = memo(function TimelineImageCard({
    item,
    onImageClick,
    onToggleSelection,
    selectionMode,
    isSelected,
    isFavorite,
    onToggleFavorite
}) {
    // Handle both ISO strings (V2) and UNIX timestamps (legacy)
    const dateValue = item.date || item.mtime;
    const timestamp = typeof dateValue === 'string' ? new Date(dateValue) : new Date(dateValue * 1000);
    const timeString = timestamp.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit'
    });

    const checkpointDisplayName = getCheckpointDisplayName(item);

    const handleClick = () => {
        if (selectionMode) {
            onToggleSelection?.(assetPath(item));
        } else {
            onImageClick?.(item);
        }
    };

    return (
        <div
            className={`group relative bg-gray-800 rounded-lg border transition-all cursor-pointer hover:shadow-lg hover:shadow-blue-500/10 ${isSelected
                ? 'border-blue-500 ring-2 ring-blue-500/50'
                : 'border-gray-700 hover:border-gray-600'
                }`}
            onClick={handleClick}
        >
            <div className="flex gap-4 p-4">
                {/* Image Preview */}
                <div className="relative flex-shrink-0 w-32 h-32 bg-gray-900 rounded-lg overflow-hidden">
                    <ProgressiveImage
                        blurhash={item.blurhash}
                        src={assetUrl(assetPath(item))}
                        thumb={item.thumb ? `${item.thumb}` : null}
                        medium={item.medium ? `${item.medium}` : null}
                        alt={item.name}
                        size="thumb"
                        className="w-full h-full object-cover"
                    />

                    {/* Selection Indicator */}
                    {selectionMode && isSelected && (
                        <div className="absolute inset-0 bg-blue-500/20 flex items-center justify-center">
                            <div className="w-8 h-8 bg-blue-500 rounded-full flex items-center justify-center">
                                <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                </svg>
                            </div>
                        </div>
                    )}
                </div>

                {/* Metadata */}
                <div className="flex-1 min-w-0 flex flex-col justify-between">
                    <div>
                        <div className="flex items-start justify-between gap-2 mb-2">
                            <h4 className="text-sm font-medium text-gray-200 truncate" title={item.name}>
                                {item.name}
                            </h4>
                            <div className="flex items-center gap-2 flex-shrink-0">
                                <span className="text-xs text-gray-500 flex items-center gap-1">
                                    <Clock size={12} />
                                    {timeString}
                                </span>
                                {!selectionMode && onToggleFavorite && (
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onToggleFavorite(assetPath(item));
                                        }}
                                        className="p-1.5 rounded-full hover:bg-gray-700 transition-colors"
                                        title={isFavorite ? 'Remove from favorites' : 'Add to favorites'}
                                        aria-label={isFavorite ? 'Remove from favorites' : 'Add to favorites'}
                                        aria-pressed={isFavorite}
                                    >
                                        <svg
                                            className={`w-4 h-4 ${isFavorite ? 'fill-yellow-400 text-yellow-400' : 'text-gray-500'}`}
                                            fill={isFavorite ? 'currentColor' : 'none'}
                                            stroke="currentColor"
                                            viewBox="0 0 24 24"
                                        >
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
                                        </svg>
                                    </button>
                                )}
                            </div>
                        </div>

                        {item.prompt && (
                            <p className="text-xs text-gray-400 line-clamp-2 mb-2 break-words">
                                {item.prompt}
                            </p>
                        )}
                    </div>

                    {/* Quick Stats */}
                    <div className="flex items-center gap-3 text-xs text-gray-500 min-w-0 flex-wrap">
                        {item.width && item.height && (
                            <span className="flex items-center gap-1">
                                <ImageIcon size={12} />
                                {item.width}×{item.height}
                            </span>
                        )}
                        {checkpointDisplayName && (
                            <span className="truncate max-w-[200px] min-w-0" title={checkpointDisplayName}>
                                {checkpointDisplayName}
                            </span>
                        )}
                        {item.steps && (
                            <span>{item.steps} steps</span>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
});
