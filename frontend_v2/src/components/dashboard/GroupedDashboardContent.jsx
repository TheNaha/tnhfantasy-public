import { memo, useCallback } from "react";
import { motion } from 'framer-motion';
import { Calendar, Check, Star } from 'lucide-react';

import FeedCard from './FeedCard';
import ImageGroup from './ImageGroup';
import JobCard from './JobCard';
import ProgressiveImage from '../ProgressiveImage';
import { getCheckpointDisplayName } from '../../utils/modelDisplay';
import { assetUrl, thumbUrl, assetPath } from '../../utils/assetUrl';
import { formatTimestamp } from '../../utils/dateTime';
import { useWindowVirtualizer } from '@tanstack/react-virtual';



// ⚡ Bolt: Extract inner item renderers into memoized components to prevent re-rendering all DOM nodes
// for unselected items when the parent's `selectedFiles` Set changes.
const GridSingleImageCard = memo(function GridSingleImageCard({ item, selected, selectionMode, isFavorite, toggleSelection, handleImageClick, handleToggleFavorite }) {
    const onCardClick = useCallback(() => {
        if (selectionMode) {
            toggleSelection(assetPath(item));
        } else {
            handleImageClick(item);
        }
    }, [selectionMode, toggleSelection, handleImageClick, item]);

    const onFavoriteClick = useCallback((event) => {
        event.stopPropagation();
        handleToggleFavorite(assetPath(item));
    }, [handleToggleFavorite, item]);

    return (
        <div
            className={`group relative aspect-square bg-[#0B0E14] rounded-2xl overflow-hidden transition-all duration-500 ease-out hover:shadow-2xl hover:shadow-blue-500/10 hover:-translate-y-1 ${selected ? 'ring-2 ring-blue-500 ring-offset-2 ring-offset-[#0B0E14]' : ''}`}
            onClick={onCardClick}
            role="img"
            aria-label={item.prompt ? `AI generated image: ${item.prompt.slice(0, 100)}${item.prompt.length > 100 ? '...' : ''}` : `Generated image ${item.name}`}
        >
            <div className="w-full h-full relative">
                <ProgressiveImage
                    blurhash={item.blurhash}
                    src={assetUrl(assetPath(item))}
                    medium={item.thumbnail_medium || thumbUrl(assetPath(item))}
                    alt={item.name}
                    size="medium"
                    className="w-full h-full object-cover transition-transform duration-700 ease-out group-hover:scale-105"
                />
                
                {/* Premium Dark Glass Hover Overlay */}
                <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent opacity-0 group-hover:opacity-100 transition-all duration-300 ease-out flex flex-col justify-end p-4">
                    <div className="translate-y-4 group-hover:translate-y-0 transition-transform duration-300 ease-out">
                        {item.prompt && (
                            <p className="text-sm font-medium text-white line-clamp-2 leading-tight drop-shadow-md">
                                {item.prompt}
                            </p>
                        )}
                        {item.checkpoint && (
                            <p className="text-[10px] uppercase tracking-wider text-blue-300 mt-2 font-bold drop-shadow-md">
                                {getCheckpointDisplayName(item.checkpoint)}
                            </p>
                        )}
                    </div>
                </div>

                {isFavorite && (
                    <div className="absolute top-3 right-3 text-yellow-400 drop-shadow-[0_0_8px_rgba(250,204,21,0.6)]">
                        <Star size={20} fill="currentColor" />
                    </div>
                )}
            </div>
            {selectionMode && (
                <div className={`absolute top-3 left-3 p-1.5 rounded-full backdrop-blur-md shadow-lg transition-colors ${selected ? 'bg-blue-500 text-white' : 'bg-black/50 border border-white/20 text-white/70 hover:bg-black/70'}`}>
                    <Check size={14} strokeWidth={3} />
                </div>
            )}

            {!selectionMode && (
                <button
                    onClick={onFavoriteClick}
                    className="absolute top-3 right-3 p-2 rounded-full bg-black/40 hover:bg-black/70 border border-white/10 backdrop-blur-md opacity-0 group-hover:opacity-100 transition-all duration-200 hover:scale-110 active:scale-95"
                    title={isFavorite ? 'Remove from favorites' : 'Add to favorites'}
                    aria-label={isFavorite ? 'Remove from favorites' : 'Add to favorites'}
                    aria-pressed={isFavorite}
                >
                    <Star
                        size={16}
                        className={`transition-colors ${isFavorite ? 'fill-yellow-400 text-yellow-400 drop-shadow-[0_0_8px_rgba(250,204,21,0.6)]' : 'text-white/80 hover:text-white'}`}
                    />
                </button>
            )}
        </div>
    );
});

const ListImageGroupCard = memo(function ListImageGroupCard({ item, selected, selectionMode, handleImageClick, handleImageGroupSelection }) {
    const onCardClick = useCallback(() => {
        handleImageClick({ ...item.images[0], siblingImages: item.images, associatedJob: item.job });
    }, [handleImageClick, item]);

    const onSelectionClick = useCallback((event) => {
        event.stopPropagation();
        handleImageGroupSelection(item.images);
    }, [handleImageGroupSelection, item.images]);

    return (
        <div
            className={`flex items-center gap-4 glass-panel p-3 rounded-2xl transition-all duration-300 cursor-pointer group hover:-translate-y-0.5 hover:shadow-xl ${selected ? 'border-blue-500 bg-blue-500/10 shadow-[0_0_15px_rgba(59,130,246,0.15)]' : 'border-white/5 hover:border-white/10'}`}
            onClick={onCardClick}
        >
            {selectionMode && (
                <div
                    className={`w-6 h-6 rounded-full border-2 flex items-center justify-center transition-colors ${selected ? 'bg-blue-500 border-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)]' : 'border-gray-500 group-hover:border-gray-400'}`}
                    onClick={onSelectionClick}
                >
                    {selected && <Check size={14} strokeWidth={3} className="text-white" />}
                </div>
            )}
            <div className="relative flex-shrink-0 w-32 shadow-lg">
                <div className="relative bg-[#0B0E14] rounded-xl overflow-hidden group-hover:ring-2 ring-blue-500/30 transition-all">
                    <ProgressiveImage
                        blurhash={item.images[0].blurhash}
                        src={assetUrl(assetPath(item.images[0]))}
                        medium={item.images[0].thumbnail_medium || thumbUrl(assetPath(item.images[0]))}
                        alt={item.images[0].name}
                        size="medium"
                        aspectRatio="auto"
                        className="w-full object-cover transition-transform duration-500 group-hover:scale-105"
                    />
                </div>
                <div className="absolute -bottom-2 -right-2 bg-gradient-to-r from-purple-500 to-blue-500 text-white text-xs px-2 py-0.5 rounded-full font-bold shadow-[0_0_10px_rgba(168,85,247,0.5)] border border-white/20">
                    {item.images.length}
                </div>
            </div>
            <div className="flex-1 min-w-0 pl-2">
                <h4 className="text-sm font-semibold text-white truncate group-hover:text-blue-400 transition-colors">{item.images.length} images grouped</h4>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1.5 text-xs text-gray-400 font-medium">
                    <span className="flex items-center gap-1.5"><Calendar size={12} className="text-gray-500" />{formatTimestamp(item.date || item.mtime)}</span>
                    <span className="truncate max-w-[220px] text-blue-300/80" title={getCheckpointDisplayName(item.images[0]) || 'Unknown Model'}>
                        {getCheckpointDisplayName(item.images[0]) || 'Unknown Model'}
                    </span>
                </div>
            </div>
        </div>
    );
});

const ListSingleImageCard = memo(function ListSingleImageCard({ item, selected, selectionMode, handleImageClick, toggleSelection }) {
    const onCardClick = useCallback(() => {
        if (selectionMode) {
            toggleSelection(assetPath(item));
        } else {
            handleImageClick(item);
        }
    }, [selectionMode, toggleSelection, handleImageClick, item]);

    const onImageOnlyClick = useCallback((event) => {
        event.stopPropagation();
        handleImageClick(item);
    }, [handleImageClick, item]);

    return (
        <div
            className={`flex items-center gap-4 glass-panel p-3 rounded-2xl transition-all duration-300 cursor-pointer group hover:-translate-y-0.5 hover:shadow-xl ${selected ? 'border-blue-500 bg-blue-500/10 shadow-[0_0_15px_rgba(59,130,246,0.15)]' : 'border-white/5 hover:border-white/10'}`}
            onClick={onCardClick}
        >
            {selectionMode && (
                <button
                    aria-label={selected ? 'Deselect image' : 'Select image'}
                    aria-pressed={selected}
                    className={`w-6 h-6 rounded-full border-2 flex items-center justify-center outline-none transition-colors ${selected ? 'bg-blue-500 border-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)]' : 'border-gray-500 group-hover:border-gray-400'}`}
                >
                    {selected && <Check size={14} strokeWidth={3} className="text-white" aria-hidden="true" />}
                </button>
            )}
            <button
                onClick={onImageOnlyClick}
                aria-label="View full image"
                className="flex-shrink-0 w-32 bg-[#0B0E14] rounded-xl overflow-hidden cursor-pointer group-hover:ring-2 ring-blue-500/30 outline-none transition-all block p-0 text-left border-none shadow-lg"
            >
                <ProgressiveImage
                    blurhash={item.blurhash}
                    src={assetUrl(assetPath(item))}
                    medium={item.thumbnail_medium || thumbUrl(assetPath(item))}
                    alt={item.name}
                    size="medium"
                    aspectRatio="auto"
                    className="w-full object-cover transition-transform duration-500 group-hover:scale-105"
                />
            </button>
            <div className="flex-1 min-w-0 pl-2">
                <h4 className="text-sm font-semibold text-white truncate group-hover:text-blue-400 transition-colors">{item.name}</h4>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1.5 text-xs text-gray-400 font-medium">
                    <span className="flex items-center gap-1.5"><Calendar size={12} className="text-gray-500" />{formatTimestamp(item.date || item.mtime)}</span>
                    <span className="text-gray-500">{(item.size / 1024 / 1024).toFixed(2)} MB</span>
                    <span className="truncate max-w-[220px] text-blue-300/80" title={getCheckpointDisplayName(item) || 'Unknown Model'}>
                        {getCheckpointDisplayName(item) || 'Unknown Model'}
                    </span>
                </div>
            </div>
        </div>
    );
});

const DefaultImageGroupImageCard = memo(function DefaultImageGroupImageCard({ image, item, handleImageClick }) {
    const onCardClick = useCallback(() => {
        handleImageClick({ ...image, siblingImages: item.images, associatedJob: item.job });
    }, [handleImageClick, image, item]);

    return (
        <div
            className="aspect-square bg-[#0B0E14] rounded-xl overflow-hidden cursor-pointer hover:ring-2 hover:ring-purple-500 transition-all duration-300 group shadow-lg"
            onClick={onCardClick}
        >
            <ProgressiveImage
                blurhash={image.blurhash}
                src={assetUrl(image.name)}
                medium={image.thumbnail_medium || thumbUrl(image.name)}
                alt={image.name}
                size="medium"
                className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
            />
        </div>
    );
});

// ⚡ Bolt: Wrap the entire container in memo to prevent expensive re-renders on unrelated parent updates
export default memo(function GroupedDashboardContent({
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
    handleJobDelete,
}) {
    // ⚡ Bolt: Use a stable callback to prevent re-renders in memoized ImageGroup components
    const handleImageGroupSelection = useCallback((images) => {
        images.forEach((image) => toggleSelection(assetPath(image)));
    }, [toggleSelection]);

    const virtualizer = useWindowVirtualizer({
        count: sortedGroupedEntries.length,
        estimateSize: (index) => {
            const itemCount = sortedGroupedEntries[index]?.[1]?.length || 1;
            if (viewMode === 'grid') {
                return Math.max(320, Math.min(1800, 180 + Math.ceil(itemCount / Math.max(gridCols, 1)) * 260));
            }
            if (viewMode === 'list') {
                return Math.max(220, Math.min(2200, 120 + itemCount * 180));
            }
            return Math.max(280, Math.min(2000, 160 + itemCount * 220));
        },
        getItemKey: (index) => sortedGroupedEntries[index]?.[0] || `group-${index}`,
        overscan: 2,
    });

    return (
        <div
            style={{
                height: `${virtualizer.getTotalSize()}px`,
                position: 'relative',
                width: '100%',
                overflow: 'hidden',
            }}
        >
            {virtualizer.getVirtualItems().map((virtualItem) => {
                const [date, groupItems] = sortedGroupedEntries[virtualItem.index];
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
                        paddingBottom: '2rem'
                    }}
                >
                    {date !== 'Random' && (
                        <h3 className="text-gray-500 font-medium mb-4 flex items-center gap-2">
                            <Calendar size={16} /> {formatDateLabel(date)}
                        </h3>
                    )}
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
                                        <JobCard job={item} onClick={handleJobClick} onDelete={handleJobDelete} />
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
                                        <GridSingleImageCard
                                            item={item}
                                            selected={selectedFiles.has(item.name)}
                                            selectionMode={selectionMode}
                                            isFavorite={isFavorite(item.name)}
                                            toggleSelection={toggleSelection}
                                            handleImageClick={handleImageClick}
                                            handleToggleFavorite={handleToggleFavorite}
                                        />
                                    )}
                                </motion.div>
                            ))}
                        </div>
                    ) : viewMode === 'list' ? (
                        <div className="space-y-2">
                            {groupItems.map((item) => (
                                item.type === 'job' ? (
                                    <JobCard key={item.id} job={item} onClick={handleJobClick} onDelete={handleJobDelete} />
                                ) : item.type === 'imageGroup' ? (
                                    <ListImageGroupCard
                                        key={item.id}
                                        item={item}
                                        selected={item.images.some((image) => selectedFiles.has(image.name))}
                                        selectionMode={selectionMode}
                                        handleImageClick={handleImageClick}
                                        handleImageGroupSelection={handleImageGroupSelection}
                                    />
                                ) : (
                                    <ListSingleImageCard
                                        key={item.name}
                                        item={item}
                                        selected={selectedFiles.has(item.name)}
                                        selectionMode={selectionMode}
                                        handleImageClick={handleImageClick}
                                        toggleSelection={toggleSelection}
                                    />
                                )
                            ))}
                        </div>
                    ) : (
                        <div className="space-y-4 md:space-y-8 max-w-3xl mx-auto">
                            {groupItems.map((item) => (
                                item.type === 'job' ? (
                                    <JobCard key={item.id} job={item} onClick={handleJobClick} onDelete={handleJobDelete} />
                                ) : item.type === 'imageGroup' ? (
                                    <div key={item.id} className="bg-gray-800/50 rounded-xl p-4 border border-gray-700">
                                        <div className="flex items-center gap-2 mb-3">
                                            <span className="text-sm text-gray-400">{item.images.length} images from batch</span>
                                        </div>
                                        <div className="grid grid-cols-2 gap-2">
                                            {item.images.map((image) => (
                                                <DefaultImageGroupImageCard
                                                    key={image.name}
                                                    image={image}
                                                    item={item}
                                                    handleImageClick={handleImageClick}
                                                />
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
                );
            })}
        </div>
    );
});
