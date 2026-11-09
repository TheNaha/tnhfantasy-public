import { memo, useCallback, useLayoutEffect, useRef, useState } from "react";
import { motion } from 'framer-motion';
import { Calendar, Check, ChevronDown, Layers, Loader2, Star, Copy, Wand2 } from 'lucide-react';
import { copyToClipboard } from '../../utils/clipboard';
import toast from 'react-hot-toast';
import FeedCard from './FeedCard';
import ImageGroup from './ImageGroup';
import JobCard from './JobCard';
import ProgressiveImage from '../ProgressiveImage';
import ClickableCard from '../common/ClickableCard';
import { SessionBadges } from './SessionPanel';
import { getCheckpointDisplayName } from '../../utils/modelDisplay';
import { getAssetPrompt } from '../../utils/assetMetadata';
import { assetUrl, thumbUrl, assetPath } from '../../utils/assetUrl';
import { formatTimestamp } from '../../utils/dateTime';
import { formatBytes } from '../../utils/bytes';
import { useSessionAssets } from '../../hooks/useSessions';
import { toLightboxImage } from '../../utils/lightboxImage';
import { useListVirtualizer } from '../../hooks/useScrollRoot';

// Every virtual item is rendered with `paddingBottom: '2rem'`, so the estimate
// has to include it. It did not: a collapsed session item measured 135px
// (103px card + 32px padding) against an estimate of 148px, so every row was
// over-estimated by 13px and the list got *shorter* as you scrolled — measured
// `scrollHeight` falling 15380 -> 15198 across 2000px of scrolling. That is the
// jump: the total length of the list changed under the scroll position, so
// everything below the viewport moved.
//
// Keep these as named parts so the relationship stays visible and the constant
// cannot drift from the markup again. If `glass-panel p-4` or the padding
// changes, these are the numbers to re-measure.
/* Filmstrip geometry.

   Two rows of fixed-size tiles. The tile size and the row count are both fixed
   so the strip's height never depends on how many images a session holds — which
   is the whole reason the list used to shrink under the scroll position. Only the
   *count* of tiles varies with the card's width, and that is measured rather than
   guessed, so a narrow phone gets fewer, larger tiles instead of eight squished
   slivers.
*/
const SESSION_STRIP_TILE = 104;   // px, square
const SESSION_STRIP_GAP = 6;
const SESSION_STRIP_ROWS = 2;
// Fallback before the first measurement lands, so the first paint is not a
// single over-wide row.
const SESSION_STRIP_FALLBACK_COLS = 6;

const SESSION_ITEM_PADDING = 32;   // paddingBottom: 2rem on every virtual item
// Measured with the two-row filmstrip: 329px = p-4 (32) + strip (2x104 + 6 gap)
// + 12 margin + name row (20) + meta row (16) + badge row (18) + chevron row.
// Re-measure this if the strip geometry, the tile size or the padding changes —
// an estimate that does not match the rendered item is what made this list
// shrink under the scroll position.
const SESSION_CARD_HEIGHT = 329;
const SESSION_HEADER_HEIGHT = SESSION_CARD_HEIGHT + SESSION_ITEM_PADDING;
const SESSION_MEMBER_ROW_HEIGHT = 116;
const SESSION_MEMBER_COLUMNS = 6;
const SESSION_MEMBER_ROW_CAP = 6;

/**
 * The image's real aspect ratio, as a CSS value.
 *
 * The list and grid views hard-coded `aspectRatio="auto"` on
 * `ProgressiveImage`, which is the one setting that reserves NO space: the box
 * is a flat `h-32` until the bytes arrive and then snaps to the image's natural
 * height. Every thumbnail that decoded moved everything below it, and since a
 * whole day is one virtual item the shifts compounded — measured, a single day
 * group going 1676px -> 3296px as its second page of images loaded, with
 * `scrollHeight` jumping 2386 -> 4134. That is the "infinite scroll is jumpy"
 * symptom: the total length of the list changing under the scroll position.
 *
 * The assets carry `width`/`height` (and the same under `metadata`), so the box
 * can be reserved exactly. That also stops the grid cropping: with a real ratio
 * `ProgressiveImage` fills the box with `object-cover`, and because the box now
 * matches the image there is nothing to crop. Previously the portrait images in
 * this library were letterboxed into a 128px column at wildly varying heights.
 */
function aspectRatioFor(item) {
    const w = Number(item?.width) || Number(item?.metadata?.width) || 0;
    const h = Number(item?.height) || Number(item?.metadata?.height) || 0;
    if (!(w > 0) || !(h > 0)) return LIBRARY_DEFAULT_ASPECT;
    // Reduce, so 1024x1024 becomes "1 / 1" rather than a pair of four-digit ints.
    const gcd = (a, b) => (b ? gcd(b, a % b) : a);
    const g = gcd(w, h);
    return `${Math.round(w / g)} / ${Math.round(h / g)}`;
}

// Most of this library is SDXL portrait (832x1216 is 2:3), so an unknown
// dimension gets the common shape rather than a square, which would over- or
// under-shoot for most rows.
const LIBRARY_DEFAULT_ASPECT = '2 / 3';


function estimateSessionUnitSize(item, expanded, gridCols) {
    const collapsed = SESSION_HEADER_HEIGHT;
    if (!expanded) return collapsed;
    const columns = Math.max(3, Math.min(SESSION_MEMBER_COLUMNS, gridCols || SESSION_MEMBER_COLUMNS));
    const rows = Math.min(SESSION_MEMBER_ROW_CAP, Math.ceil((item?.imageCount || 0) / columns));
    return collapsed + rows * SESSION_MEMBER_ROW_HEIGHT;
}

const SessionGroupCard = memo(function SessionGroupCard({ item, expanded, onToggleExpand, onImageClick, selectionMode, selectedFiles, toggleSelection }) {
    // The loaded assets, shaped once. Both the click target and the
    // lightbox's navigation list come from here, so they can never disagree
    // about what "this session" contains.
    /* Fetched for collapsed sessions as well, not only when expanded: the
       filmstrip is the reason this view is media-oriented, and it cannot render
       from `item.thumbnail` alone. The virtualizer keeps ~a dozen rows mounted,
       so this is a dozen small cached requests (`staleTime` 5 min) rather than
       one per session in a 1,400-session library. */
    const { data, isLoading, error } = useSessionAssets(item.sessionId, { enabled: true });
    const stripAssets = data?.assets;

    /* Tile count from the measured width, so the two-row strip is always two
       rows. `ResizeObserver` rather than a one-shot read: the card is full-width
       on desktop and a fraction of it on a phone, and the sidebar collapses on
       rotation. */
    const stripRef = useRef(null);
    const [stripCols, setStripCols] = useState(SESSION_STRIP_FALLBACK_COLS);
    useLayoutEffect(() => {
        const node = stripRef.current;
        if (!node) return undefined;
        const measure = () => {
            const w = node.clientWidth;
            if (!w) return;
            const cols = Math.max(2, Math.floor((w + SESSION_STRIP_GAP) / (SESSION_STRIP_TILE + SESSION_STRIP_GAP)));
            setStripCols((prev) => (prev === cols ? prev : cols));
        };
        measure();
        const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
        ro?.observe(node);
        return () => ro?.disconnect();
    }, []);

    // One slot is spent on the "+N" tile whenever there is an overflow.
    const total = stripAssets?.length ?? item.imageCount ?? 0;
    const capacity = stripCols * SESSION_STRIP_ROWS;
    const hasOverflow = total > capacity;
    const stripSlots = hasOverflow ? capacity - 1 : capacity;
    const stripOverflow = Math.max(0, total - stripSlots);

    /* Note on the `AUTO-DETECTED` badge: it does look like noise in a library
       where most sessions are auto-detected, and removing it was tried. It is
       load-bearing — `SessionBadges` pairs it with a `Curated` badge and
       `GroupedDashboardContent.sessions.test.jsx` pins that a detected session
       shows "Auto-detected" and a hand-made one shows "Curated". It answers
       "can I rename and re-group this freely, or is the grouping machine-made",
       which is not the same question as "is this a session".

       The seed-based names (`Seed 2557611075753025`) are the weaker half of this
       view, and they are not fixable here either: the grouping item is built from
       the session record alone (`utils/dashboardItems.js` — no asset metadata), so
       the first image's prompt is not on the client, and the detector deliberately
       never reads `assets.metadata_` (~70 MB on this deployment). The name is
       `Seed <n>` because the seed is the column it groups on. Fixing that means
       returning a prompt from the sessions endpoint — a real change, not a
       cosmetic one. */

    return (
        <section
            className="glass-panel rounded-2xl border border-white/5 p-4"
            aria-label={`Session ${item.name}`}
        >
            {/* The filmstrip.

                A session is a *group of images*, and the collapsed card used to
                show one 56px thumbnail of it — so the media-oriented view showed
                almost no media and you had to expand every session to see what it
                held. The strip puts the images first and the metadata second,
                which is the order you scan a session in.

                Two rows of fixed 104px tiles rather than one row of eight: eight
                slivers across a card is neither previewable nor tappable, and the
                tiles were also too short to read as images. The tile count is
                measured from the card's width (`stripCols`), so a narrow phone
                gets fewer and larger tiles rather than the same eight squeezed
                harder — and the row count stays at two, which is what keeps the
                card height independent of the image count and `estimateSize`
                exact.

                Each tile opens the same lightbox the grid opens, with the session's
                images as the swipable siblings, so the media here is navigable
                rather than decorative. */}
            <div
                ref={stripRef}
                className="grid gap-1.5 mb-3"
                style={{
                    gridTemplateColumns: `repeat(${stripCols}, minmax(0, 1fr))`,
                    height: SESSION_STRIP_ROWS * SESSION_STRIP_TILE + (SESSION_STRIP_ROWS - 1) * SESSION_STRIP_GAP,
                }}
            >
                {isLoading && Array.from({ length: Math.min(capacity, Math.max(2, item.imageCount || 2)) }).map((_, i) => (
                    <span
                        key={`ph-${i}`}
                        className="rounded-lg bg-gray-800/60 animate-pulse"
                        style={{ height: SESSION_STRIP_TILE }}
                    />
                ))}

                {!isLoading && (stripAssets || []).slice(0, stripSlots).map((asset) => (
                    <button
                        type="button"
                        key={asset.id}
                        aria-label={asset.relative_path}
                        onClick={(e) => {
                            e.stopPropagation();
                            if (selectionMode) {
                                toggleSelection?.(asset.relative_path);
                                return;
                            }
                            onImageClick?.(
                                toLightboxImage(asset),
                                (stripAssets || []).map(toLightboxImage).filter(Boolean),
                            );
                        }}
                        className="relative rounded-lg overflow-hidden bg-gray-800 focus-visible:ring-2 focus-visible:ring-blue-500"
                        style={{ height: SESSION_STRIP_TILE }}
                    >
                        <ProgressiveImage
                            blurhash={asset.blurhash}
                            src={assetUrl(assetPath(asset))}
                            medium={asset.thumbnail_medium || thumbUrl(assetPath(asset))}
                            alt=""
                            size="medium"
                            aspectRatio="1 / 1"
                            objectFit="cover"
                            className="w-full h-full"
                        />
                    </button>
                ))}

                {stripOverflow > 0 && (
                    <span
                        className="rounded-lg bg-gray-800/80 flex items-center justify-center text-sm font-semibold text-gray-300"
                        style={{ height: SESSION_STRIP_TILE }}
                    >
                        +{stripOverflow}
                    </span>
                )}
            </div>

            <button
                type="button"
                onClick={onToggleExpand}
                aria-expanded={expanded}
                className="w-full flex items-center gap-3 text-left"
            >
                <span className="flex-1 min-w-0">
                    <span className="flex items-center gap-2">
                        <span
                            className="text-sm font-semibold text-white truncate"
                            title={item.name}
                        >
                            {item.name}
                        </span>
                    </span>
                    <span className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-400 font-medium">
                        <span>{item.imageCount} image{item.imageCount === 1 ? '' : 's'}</span>
                        <span className="flex items-center gap-1.5">
                            <Calendar size={12} className="text-gray-500" aria-hidden="true" />
                            {formatTimestamp(item.startAt || item.updatedAt)}
                        </span>
                    </span>
                    <SessionBadges
                        autoDetected={item.autoDetected}
                        locked={item.locked}
                        className="mt-1.5"
                    />
                </span>

                <ChevronDown
                    size={18}
                    aria-hidden="true"
                    className={`text-gray-500 flex-shrink-0 transition-transform ${expanded ? 'rotate-180' : ''}`}
                />
            </button>

            {expanded && (
                <div className="mt-4">
                    {isLoading && (
                        <div className="flex items-center gap-2 py-6 justify-center text-sm text-gray-400">
                            <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                            Loading images…
                        </div>
                    )}

                    {error && (
                        <p role="alert" className="text-sm text-red-300">
                            {error.message || 'Could not load this session’s images.'}
                        </p>
                    )}

                    {!isLoading && !error && (data?.assets?.length ?? 0) === 0 && (
                        <p className="py-6 text-center text-sm text-gray-500">
                            This session has no images.
                        </p>
                    )}

                    {!isLoading && !error && (data?.assets?.length ?? 0) > 0 && (
                        <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(96px, 1fr))' }}>
                            {/* These were plain <img> with no handler, so the one
                                place a session actually showed its images was the
                                one place you could not open one. The lightbox reads
                                `relative_path` through `assetPath`, which is exactly
                                the field the session-assets endpoint returns, so the
                                same modal the grid opens opens from here. */}
                            {data.assets.map((asset) => {
                                const selected = selectedFiles?.has(asset.relative_path) ?? false;
                                return (
                                    <button
                                        type="button"
                                        key={asset.id}
                                        onClick={() => {
                                            if (selectionMode) {
                                                toggleSelection?.(asset.relative_path);
                                                return;
                                            }
                                            onImageClick?.(
                                                toLightboxImage(asset),
                                                // The siblings, so the lightbox
                                                // can be swiped within this group.
                                                (data?.assets || []).map(toLightboxImage).filter(Boolean),
                                            );
                                        }}
                                        title={selectionMode
                                            ? (selected ? 'Deselect' : 'Select')
                                            : 'Open image details'}
                                        aria-label={asset.relative_path}
                                        aria-pressed={selectionMode ? selected : undefined}
                                        className={`relative block w-full aspect-square rounded-lg overflow-hidden bg-gray-800 border-2 transition-colors ${
                                            selected ? 'border-yellow-400' : 'border-transparent hover:border-purple-500'
                                        }`}
                                    >
                                        <img
                                            src={thumbUrl(asset.relative_path)}
                                            alt={asset.relative_path}
                                            loading="lazy"
                                            className="w-full h-full object-cover"
                                        />
                                    </button>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}
        </section>
    );
});



// ⚡ Bolt: Extract inner item renderers into memoized components to prevent re-rendering all DOM nodes
// for unselected items when the parent's `selectedFiles` Set changes.
const GridSingleImageCard = memo(function GridSingleImageCard({ item, selected, selectionMode, isFavorite, toggleSelection, handleImageClick, handleToggleFavorite, onQuickReuse }) {
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

    const onCopyPromptClick = useCallback(async (event) => {
        event.stopPropagation();
        const promptText = getAssetPrompt(item);
        if (!promptText) return;
        const ok = await copyToClipboard(promptText);
        if (ok) toast.success('Prompt copied');
    }, [item]);

    const onReuseClick = useCallback((event) => {
        event.stopPropagation();
        if (onQuickReuse) onQuickReuse(item);
    }, [onQuickReuse, item]);
    // Generation metadata lives under `item.metadata`; nothing hoists it to the
    // top level, so reading `item.prompt` directly was always undefined and the
    // hover overlay below never rendered a word.
    const cardPrompt = getAssetPrompt(item);

    return (
        // `ClickableCard`, not a hand-rolled `div`. This root used to be
        // `role="img"`, a leaf role with children-presentational semantics: the
        // whole subtree collapsed into one image node and the real favourite
        // `<button aria-pressed>` inside it was pruned from the accessibility
        // tree. It also had no `tabIndex`, so opening the lightbox was
        // mouse-only. See `common/ClickableCard.jsx`.
        <ClickableCard
            className={`group relative aspect-square bg-[#0B0E14] rounded-2xl overflow-hidden transition-all duration-500 ease-out hover:shadow-2xl hover:shadow-blue-500/10 hover:-translate-y-1 ${selected ? 'ring-2 ring-blue-500 ring-offset-2 ring-offset-[#0B0E14]' : ''}`}
            onActivate={onCardClick}
            ariaLabel={cardPrompt ? `AI generated image: ${cardPrompt.slice(0, 100)}${cardPrompt.length > 100 ? '...' : ''}` : `Generated image ${item.name}`}
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
                
                {/* Premium Dark Glass Hover Overlay.

                    `hidden sm:block` on the WHOLE overlay, not just the model
                    line. On a touch device there is no hover, so :hover latches on
                    tap and the caption then covers the image with nothing able to
                    dismiss it. A hover-only affordance has no meaning where
                    pointers do not exist, so it is not rendered there at all.
                    Everything it showed is in the lightbox one tap away. */}
                <div className="hidden sm:absolute sm:inset-0 sm:bg-gradient-to-t sm:from-black/90 sm:via-black/40 sm:to-transparent sm:opacity-0 sm:group-hover:opacity-100 transition-all duration-300 ease-out flex flex-col justify-end p-4">
                    <div className="translate-y-4 group-hover:translate-y-0 transition-transform duration-300 ease-out">
                        {cardPrompt && (
                            <p className="text-sm font-medium text-white line-clamp-2 leading-tight drop-shadow-md">
                                {cardPrompt}
                            </p>
                        )}
                        {/* Pass the whole item: getCheckpointDisplayName resolves
                            source.checkpoint ?? source.metadata?.checkpoint itself.
                            Passing item.checkpoint made this line unrenderable — and
                            the value it read was undefined anyway, because nothing
                            hoists checkpoint out of `metadata`.

                            Clamped to one line, and hidden on coarse pointers.
                            Both because this string is a merged CivitAI filename —
                            "✨ JANKU Trained + Chenkin & NoobAI + RouWei
                            Illustrious XL ✨" is a real `display_name` here — and
                            unclamped it wrapped to three lines on a phone card.

                            The coarse-pointer rule is the bug half. This whole
                            overlay is `opacity-0 group-hover:opacity-100`, and a
                            touch device has no hover: a tap sets :hover and it
                            STAYS set, so on a phone the model line appeared
                            permanently over the image. There is no pointer to move
                            away, so there is nothing to restore it — the
                            affordance was broken on touch rather than merely noisy.
                            The model is still one tap away in the lightbox. */}
                        {getCheckpointDisplayName(item) && (
                            <p
                                title={getCheckpointDisplayName(item)}
                                className="hidden sm:block sm:line-clamp-1 text-xs uppercase tracking-wider text-blue-300 mt-2 font-bold drop-shadow-md truncate"
                            >
                                {getCheckpointDisplayName(item)}
                            </p>
                        )}

                        {(cardPrompt || item?.metadata) && (
                            <div className="mt-2.5 flex items-center gap-1.5">
                                {cardPrompt && (
                                    <button
                                        type="button"
                                        onClick={onCopyPromptClick}
                                        aria-label="Copy prompt"
                                        title="Copy prompt"
                                        className="px-2 py-1 rounded-lg bg-white/10 hover:bg-white/20 text-white text-2xs font-medium flex items-center gap-1 backdrop-blur-sm transition-colors"
                                    >
                                        <Copy size={12} aria-hidden="true" />
                                        <span>Copy</span>
                                    </button>
                                )}
                                {item?.metadata && onQuickReuse && (
                                    <button
                                        type="button"
                                        onClick={onReuseClick}
                                        aria-label="Reuse parameters"
                                        title="Reuse parameters in Generator"
                                        className="px-2 py-1 rounded-lg bg-blue-600/80 hover:bg-blue-500 text-white text-2xs font-medium flex items-center gap-1 backdrop-blur-sm transition-colors"
                                    >
                                        <Wand2 size={12} aria-hidden="true" />
                                        <span>Reuse</span>
                                    </button>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>
            {selectionMode && (
                <div className={`absolute top-3 left-3 flex h-8 w-8 items-center justify-center rounded-full backdrop-blur-md shadow-lg transition-colors ${selected ? 'bg-blue-500 text-white' : 'bg-black/50 border border-white/20 text-white/70 hover:bg-black/70'}`}>
                    <Check size={14} strokeWidth={3} />
                </div>
            )}

            {!selectionMode && (
                /* This is the only favourite control on the card now. There used
                   to be a second, bare `<Star size={20}>` at this same
                   `top-3 right-3`, shown when `isFavorite` — so a favourited card
                   rendered two stars of different sizes in one corner,
                   overlapping. The button fills its own star when favourited, so
                   the indicator was pure duplication.

                   Also `opacity-100 sm:opacity-0 sm:group-hover:opacity-100`: a
                   `group-hover:` control does not appear on a device with no
                   hover, so on a phone the favourite control was simply absent
                   and a favourited card showed a star that did nothing when
                   tapped. Fixed 32px box with a 14px star, matching the
                   selection chip opposite so the two corners line up. */
                <button
                    onClick={onFavoriteClick}
                    className="absolute top-3 right-3 flex h-8 w-8 items-center justify-center rounded-full bg-black/40 hover:bg-black/70 border border-white/10 backdrop-blur-md opacity-100 sm:opacity-0 sm:group-hover:opacity-100 focus-visible:opacity-100 transition-opacity duration-200 active:scale-95"
                    title={isFavorite ? 'Remove from favorites' : 'Add to favorites'}
                    aria-label={isFavorite ? 'Remove from favorites' : 'Add to favorites'}
                    aria-pressed={isFavorite}
                >
                    <Star
                        size={14}
                        className={`transition-colors ${isFavorite ? 'fill-yellow-400 text-yellow-400 drop-shadow-[0_0_8px_rgba(250,204,21,0.6)]' : 'text-white/80 hover:text-white'}`}
                    />
                </button>
            )}
        </ClickableCard>
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
        <ClickableCard
            className={`flex items-center gap-4 glass-panel p-3 rounded-2xl transition-all duration-300 cursor-pointer group hover:-translate-y-0.5 hover:shadow-xl ${selected ? 'border-blue-500 bg-blue-500/10 shadow-[0_0_15px_rgba(59,130,246,0.15)]' : 'border-white/5 hover:border-white/10'}`}
            onActivate={onCardClick}
            ariaLabel={getAssetPrompt(item.images[0]) ? `Group of ${item.images.length} images` : undefined}
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
                        aspectRatio={aspectRatioFor(item.images[0])}
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
        </ClickableCard>
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
        <ClickableCard
            className={`flex items-center gap-4 glass-panel p-3 rounded-2xl transition-all duration-300 cursor-pointer group hover:-translate-y-0.5 hover:shadow-xl ${selected ? 'border-blue-500 bg-blue-500/10 shadow-[0_0_15px_rgba(59,130,246,0.15)]' : 'border-white/5 hover:border-white/10'}`}
            onActivate={onCardClick}
            ariaLabel={getAssetPrompt(item) ? `Image: ${getAssetPrompt(item).slice(0, 100)}` : undefined}
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
                    aspectRatio={aspectRatioFor(item)}
                    className="w-full object-cover transition-transform duration-500 group-hover:scale-105"
                />
            </button>
            <div className="flex-1 min-w-0 pl-2">
                <h4 className="text-sm font-semibold text-white truncate group-hover:text-blue-400 transition-colors">{item.name}</h4>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1.5 text-xs text-gray-400 font-medium">
                    <span className="flex items-center gap-1.5"><Calendar size={12} className="text-gray-500" />{formatTimestamp(item.date || item.mtime)}</span>
                    <span className="text-gray-500">{formatBytes(item.size)}</span>
                    <span className="truncate max-w-[220px] text-blue-300/80" title={getCheckpointDisplayName(item) || 'Unknown Model'}>
                        {getCheckpointDisplayName(item) || 'Unknown Model'}
                    </span>
                </div>
            </div>
        </ClickableCard>
    );
});

const DefaultImageGroupImageCard = memo(function DefaultImageGroupImageCard({ image, item, handleImageClick }) {
    const onCardClick = useCallback(() => {
        handleImageClick({ ...image, siblingImages: item.images, associatedJob: item.job });
    }, [handleImageClick, image, item]);

    return (
        <ClickableCard
            className="aspect-square bg-[#0B0E14] rounded-xl overflow-hidden cursor-pointer hover:ring-2 hover:ring-purple-500 transition-all duration-300 group shadow-lg"
            onActivate={onCardClick}
            ariaLabel={image.name}
        >
            <ProgressiveImage
                blurhash={image.blurhash}
                src={assetUrl(image.name)}
                medium={image.thumbnail_medium || thumbUrl(image.name)}
                alt={image.name}
                size="medium"
                className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
            />
        </ClickableCard>
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
    onQuickReuse,
}) {
    const handleImageGroupSelection = useCallback((images) => {
        images.forEach((image) => toggleSelection(assetPath(image)));
    }, [toggleSelection]);

    const [expandedSessionIds, setExpandedSessionIds] = useState(() => new Set());

    const handleToggleSessionExpand = useCallback((sessionId) => {
        setExpandedSessionIds((current) => {
            const next = new Set(current);
            if (next.has(sessionId)) {
                next.delete(sessionId);
            } else {
                next.add(sessionId);
            }
            return next;
        });
    }, []);

    const listRef = useRef(null);
    const virtualizer = useListVirtualizer(listRef, {
        count: sortedGroupedEntries.length,
        estimateSize: (index) => {
            const groupItems = sortedGroupedEntries[index]?.[1];
            const itemCount = groupItems?.length || 1;
            if (viewMode === 'session') {
                return estimateSessionUnitSize(
                    groupItems?.[0],
                    expandedSessionIds.has(groupItems?.[0]?.sessionId),
                    gridCols,
                );
            }
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
                ref={listRef}
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
                    {date !== 'Random' && viewMode !== 'session' && (
                        <h3 className="text-gray-500 font-medium mb-4 flex items-center gap-2">
                            <Calendar size={16} /> {formatDateLabel(date)}
                        </h3>
                    )}
                    {viewMode === 'session' ? (
                        <SessionGroupCard
                            item={groupItems[0]}
                            expanded={expandedSessionIds.has(groupItems[0]?.sessionId)}
                            onToggleExpand={() => handleToggleSessionExpand(groupItems[0]?.sessionId)}
                            onImageClick={handleImageClick}
                            selectionMode={selectionMode}
                            selectedFiles={selectedFiles}
                            toggleSelection={toggleSelection}
                        />
                    ) : viewMode === 'grid' ? (
                        <div
                            className="grid gap-2 sm:gap-4"
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
                                            onQuickReuse={onQuickReuse}
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
