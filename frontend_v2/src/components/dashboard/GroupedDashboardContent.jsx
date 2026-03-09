import React from "react";
import { useCallback } from "react";
import { motion } from 'framer-motion';
import { Calendar, Check, Star } from 'lucide-react';

import FeedCard from './FeedCard';
import ImageGroup from './ImageGroup';
import JobCard from './JobCard';
import ProgressiveImage from '../ProgressiveImage';

function formatTimestamp(timestamp) {
    if (!timestamp) {
        return 'Unknown date';
    }

    let date;
    if (typeof timestamp === 'string') {
        date = new Date(timestamp.endsWith('Z') ? timestamp : `${timestamp}Z`);
    } else if (timestamp > 1e12) {
        date = new Date(timestamp);
    } else if (timestamp > 0) {
        date = new Date(timestamp * 1000);
    } else {
        return 'Unknown date';
    }

    return Number.isNaN(date.getTime()) ? 'Unknown date' : date.toLocaleString();
}

const GroupedDashboardContent = React.memo(function GroupedDashboardContent({
    viewMode,
    sortedGroupedEntries,
    formatDateLabel,
    gridCols,
    selectedFiles,
    selectionMode,
    handleJobClick,
    handleImageClick,
    toggleSelection,
    isFavorite,
    handleToggleFavorite,
    handleDelete,
}) {
    // ⚡ Bolt: Use a stable callback to prevent re-renders in memoized ImageGroup components
    const handleImageGroupSelection = useCallback((images) => {
        images.forEach((image) => toggleSelection(image.name));
    }, [toggleSelection]);

    return (
        <div className="space-y-8">
            {sortedGroupedEntries.map(([date, groupItems]) => (
                <div key={date}>
                    <h3 className="text-gray-500 font-medium mb-4 flex items-center gap-2">
                        <Calendar size={16} /> {formatDateLabel(date)}
                    </h3>
                    {viewMode === 'grid' ? (
                        <div
                            className="grid gap-4"
                            style={{ gridTemplateColumns: `repeat(${gridCols}, minmax(0, 1fr))` }}
                        >
                            {groupItems.map((item) => (
                                <motion.div
                                    initial={{ opacity: 0, scale: 0.96 }}
                                    animate={{ opacity: 1, scale: 1 }}
                                    transition={{ duration: 0.18 }}
                                    key={item.id || item.name}
                                >
                                    {item.type === 'job' ? (
                                        <JobCard job={item} onClick={handleJobClick} />
                                    ) : item.type === 'imageGroup' ? (
                                        <ImageGroup
                                            images={item.images}
                                            job={item.job}
                                            isSelected={item.images.some((image) => selectedFiles.has(image.name))}
                                            showSelectionCheckbox={selectionMode}
                                            onSelectionToggle={handleImageGroupSelection}
                                            onClick={handleImageClick}
                                        />
                                    ) : (
                                        <div
                                            className={`group relative aspect-square bg-gray-800 rounded-xl overflow-hidden border transition-all ${selectedFiles.has(item.name) ? 'border-blue-500 ring-2 ring-blue-500/50' : 'border-gray-800 hover:border-gray-600'}`}
                                            onClick={() => {
                                                if (selectionMode) {
                                                    toggleSelection(item.name);
                                                } else {
                                                    handleImageClick(item);
                                                }
                                            }}
                                            role="img"
                                            aria-label={item.prompt ? `AI generated image: ${item.prompt.slice(0, 100)}${item.prompt.length > 100 ? '...' : ''}` : `Generated image ${item.name}`}
                                        >
                                            <div className="aspect-square bg-gray-800 rounded-xl overflow-hidden group relative">
                                                <ProgressiveImage
                                                    blurhash={item.blurhash}
                                                    src={`/api/view/output/${item.name}`}
                                                    medium={item.thumbnail_medium || `/api/thumbnail/medium/${item.name}`}
                                                    alt={item.name}
                                                    size="medium"
                                                    className="w-full h-full"
                                                />
                                                <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200" />
                                                {isFavorite(item.name) && (
                                                    <div className="absolute top-2 right-2 text-yellow-400">
                                                        <Star size={20} fill="currentColor" />
                                                    </div>
                                                )}
                                            </div>
                                            {selectionMode && (
                                                <div className={`absolute top-2 right-2 p-1.5 rounded-full ${selectedFiles.has(item.name) ? 'bg-blue-500 text-white' : 'bg-black/50 text-gray-400'}`}>
                                                    <Check size={14} />
                                                </div>
                                            )}

                                            {!selectionMode && (
                                                <button
                                                    onClick={(event) => {
                                                        event.stopPropagation();
                                                        handleToggleFavorite(item.name);
                                                    }}
                                                    className="absolute top-2 right-2 p-1.5 rounded-full bg-black/50 hover:bg-black/70 backdrop-blur-sm opacity-0 group-hover:opacity-100 transition-opacity"
                                                    title={isFavorite(item.name) ? 'Remove from favorites' : 'Add to favorites'}
                                                    aria-label={isFavorite(item.name) ? 'Remove from favorites' : 'Add to favorites'}
                                                >
                                                    <Star
                                                        size={16}
                                                        className={isFavorite(item.name) ? 'fill-yellow-400 text-yellow-400' : 'text-gray-300'}
                                                    />
                                                </button>
                                            )}
                                        </div>
                                    )}
                                </motion.div>
                            ))}
                        </div>
                    ) : viewMode === 'list' ? (
                        <div className="space-y-2">
                            {groupItems.map((item) => (
                                item.type === 'job' ? (
                                    <JobCard key={item.id} job={item} onClick={handleJobClick} />
                                ) : item.type === 'imageGroup' ? (
                                    <div
                                        key={item.id}
                                        className={`flex items-center gap-4 bg-gray-800/50 p-3 rounded-lg border transition-colors cursor-pointer ${item.images.some((image) => selectedFiles.has(image.name)) ? 'border-blue-500 bg-blue-900/10' : 'border-gray-700 hover:bg-gray-800'}`}
                                        onClick={() => handleImageClick({ ...item.images[0], siblingImages: item.images, associatedJob: item.job })}
                                    >
                                        {selectionMode && (
                                            <div
                                                className={`w-5 h-5 rounded border flex items-center justify-center ${item.images.some((image) => selectedFiles.has(image.name)) ? 'bg-blue-500 border-blue-500' : 'border-gray-600'}`}
                                                onClick={(event) => {
                                                    event.stopPropagation();
                                                    handleImageGroupSelection(item.images);
                                                }}
                                            >
                                                {item.images.some((image) => selectedFiles.has(image.name)) && <Check size={12} />}
                                            </div>
                                        )}
                                        <div className="relative flex-shrink-0 w-32">
                                            <div className="relative bg-gray-800 rounded-lg overflow-hidden">
                                                <ProgressiveImage
                                                    blurhash={item.images[0].blurhash}
                                                    src={`/api/view/output/${item.images[0].name}`}
                                                    medium={item.images[0].thumbnail_medium || `/api/thumbnail/medium/${item.images[0].name}`}
                                                    alt={item.images[0].name}
                                                    size="medium"
                                                    aspectRatio="auto"
                                                    className="w-full"
                                                />
                                            </div>
                                            <div className="absolute -bottom-1 -right-1 bg-purple-500 text-white text-xs px-1.5 py-0.5 rounded font-medium">
                                                {item.images.length}
                                            </div>
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <h4 className="text-sm font-medium text-white truncate">{item.images.length} images</h4>
                                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1 text-xs text-gray-400">
                                                <span>{formatTimestamp(item.date || item.mtime)}</span>
                                            </div>
                                        </div>
                                    </div>
                                ) : (
                                    <div
                                        key={item.name}
                                        className={`flex items-center gap-4 bg-gray-800/50 p-3 rounded-lg border transition-colors cursor-pointer ${selectedFiles.has(item.name) ? 'border-blue-500 bg-blue-900/10' : 'border-gray-700 hover:bg-gray-800'}`}
                                        onClick={() => {
                                            if (selectionMode) {
                                                toggleSelection(item.name);
                                            } else {
                                                handleImageClick(item);
                                            }
                                        }}
                                    >
                                        {selectionMode && (
                                            <div className={`w-5 h-5 rounded border flex items-center justify-center ${selectedFiles.has(item.name) ? 'bg-blue-500 border-blue-500' : 'border-gray-600'}`}>
                                                {selectedFiles.has(item.name) && <Check size={12} />}
                                            </div>
                                        )}
                                        <div onClick={() => handleImageClick(item)} className="flex-shrink-0 w-32 bg-gray-800 rounded-lg overflow-hidden cursor-pointer hover:ring-2 hover:ring-blue-500 transition-all">
                                            <ProgressiveImage
                                                blurhash={item.blurhash}
                                                src={`/api/view/output/${item.name}`}
                                                medium={item.thumbnail_medium || `/api/thumbnail/medium/${item.name}`}
                                                alt={item.name}
                                                size="medium"
                                                aspectRatio="auto"
                                                className="w-full"
                                            />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <h4 className="text-sm font-medium text-white truncate">{item.name}</h4>
                                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1 text-xs text-gray-400">
                                                <span>{(item.size / 1024 / 1024).toFixed(2)} MB</span>
                                                <span>{formatTimestamp(item.date || item.mtime)}</span>
                                            </div>
                                        </div>
                                    </div>
                                )
                            ))}
                        </div>
                    ) : (
                        <div className="space-y-8 max-w-3xl mx-auto">
                            {groupItems.map((item) => (
                                item.type === 'job' ? (
                                    <JobCard key={item.id} job={item} onClick={handleJobClick} />
                                ) : item.type === 'imageGroup' ? (
                                    <div key={item.id} className="bg-gray-800/50 rounded-xl p-4 border border-gray-700">
                                        <div className="flex items-center gap-2 mb-3">
                                            <span className="text-sm text-gray-400">{item.images.length} images from batch</span>
                                        </div>
                                        <div className="grid grid-cols-2 gap-2">
                                            {item.images.map((image) => (
                                                <div
                                                    key={image.name}
                                                    className="aspect-square bg-gray-700 rounded-lg overflow-hidden cursor-pointer hover:ring-2 hover:ring-purple-500 transition-all"
                                                    onClick={() => handleImageClick({ ...image, siblingImages: item.images, associatedJob: item.job })}
                                                >
                                                    <ProgressiveImage
                                                        blurhash={image.blurhash}
                                                        src={`/api/view/output/${image.name}`}
                                                        medium={image.thumbnail_medium || `/api/thumbnail/medium/${image.name}`}
                                                        alt={image.name}
                                                        size="medium"
                                                        className="w-full h-full"
                                                    />
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                ) : (
                                    <FeedCard
                                        key={item.name}
                                        item={item}
                                        selected={selectedFiles.has(item.name)}
                                        onSelect={toggleSelection}
                                        onClick={handleImageClick}
                                        selectionMode={selectionMode}
                                        onDelete={handleDelete}
                                    />
                                )
                            ))}
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
});

export default GroupedDashboardContent;