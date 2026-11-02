import { useState, useRef, useEffect } from 'react';
import { Tag, Plus, X, Lock } from 'lucide-react';
import { useAssetTags, useAddAssetTag, useRemoveAssetTag, useTagVocabulary } from '../../hooks/useAssetTags';
import { QueryErrorState } from '../common/QueryState';

/**
 * The producer the Tags filter was missing.
 *
 * `GalleryFilterPanel` shipped a first-class `Tags` facet with a typeahead and
 * counts, and `useAssetTags` had zero importers, so a user could filter by a tag
 * that nothing in the product could create. This is the other half: an image's
 * tags, and the ability to type one. It lives in the lightbox because that is
 * where the asset id and the image the user is looking at already are.
 *
 * `auto` tags are shown but not removable — they are re-derived from the LoRAs
 * the image used, and the backend 404s a delete on one on purpose. Rendering
 * them read-only with a lock says that without the user having to try it.
 *
 * The caller keys this by asset id, so navigating between images remounts it
 * and the draft clears. An effect that reset the draft on `assetId` would
 * render the previous image's half-typed tag on the new one first.
 */
export default function AssetTagEditor({ assetId }) {
    const [draft, setDraft] = useState('');
    const [isFocused, setIsFocused] = useState(false);
    const containerRef = useRef(null);

    const { data, isLoading, isError, error, refetch } = useAssetTags(assetId);
    const addTag = useAddAssetTag(assetId);
    const removeTag = useRemoveAssetTag(assetId);
    const { data: vocabulary } = useTagVocabulary({ prefix: draft.trim() }, { enabled: isFocused && draft.trim().length > 0 });

    useEffect(() => {
        if (!isFocused) return undefined;
        const onPointerDown = (event) => {
            if (containerRef.current && !containerRef.current.contains(event.target)) {
                setIsFocused(false);
            }
        };
        document.addEventListener('mousedown', onPointerDown);
        return () => document.removeEventListener('mousedown', onPointerDown);
    }, [isFocused]);

    if (!assetId) return null;

    const tags = data?.tags || [];
    const userTags = tags.filter((t) => t.source === 'user');
    const autoTags = tags.filter((t) => t.source !== 'user');
    const alreadyOn = new Set(tags.map((t) => t.tag.toLowerCase()));
    const suggestions = (vocabulary?.tags || [])
        .filter((entry) => !alreadyOn.has(entry.tag.toLowerCase()))
        .slice(0, 8);

    const submit = async (tag) => {
        const value = tag.trim();
        if (!value) return;
        if (alreadyOn.has(value.toLowerCase())) {
            setDraft('');
            return;
        }
        try {
            await addTag.mutateAsync(value);
            setDraft('');
            setIsFocused(false);
        } catch (err) {
            console.error('Failed to add tag:', err);
        }
    };

    return (
        <div ref={containerRef} data-testid="asset-tag-editor" className="relative">
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <Tag size={12} /> Tags
            </h4>

            {isLoading ? (
                <p className="text-xs text-gray-500">Loading tags…</p>
            ) : isError ? (
                // The shared component, not a hand-rolled paragraph: this panel
                // is the only tag surface for an image, and the previous alert
                // had no retry, so a single failed GET left the tags
                // permanently unlisted until a manual reload.
                <QueryErrorState noun="tags" error={error} onRetry={refetch} className="!p-3" />
            ) : tags.length === 0 ? (
                <p className="text-xs text-gray-500 mb-2">No tags yet.</p>
            ) : (
                <ul className="flex flex-wrap gap-1.5 mb-2">
                    {userTags.map((tag) => (
                        <li key={`user-${tag.tag}`}>
                            <span className="inline-flex items-center gap-1 rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-xs text-cyan-200">
                                {tag.tag}
                                <button
                                    type="button"
                                    onClick={() => removeTag.mutate(tag.tag)}
                                    disabled={removeTag.isPending}
                                    aria-label={`Remove tag ${tag.tag}`}
                                    className="text-cyan-300/70 hover:text-cyan-100 disabled:opacity-50"
                                >
                                    <X size={11} />
                                </button>
                            </span>
                        </li>
                    ))}
                    {autoTags.map((tag) => (
                        <li key={`auto-${tag.tag}`}>
                            <span
                                className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-xs text-gray-400"
                                title="Derived from the LoRAs this image used — removed on the next rescan, so it cannot be edited here"
                            >
                                {tag.tag}
                                <Lock size={9} />
                            </span>
                        </li>
                    ))}
                </ul>
            )}

            <form
                onSubmit={(event) => { event.preventDefault(); submit(draft); }}
                className="flex items-center gap-2"
            >
                <input
                    type="text"
                    value={draft}
                    onChange={(event) => { setDraft(event.target.value); setIsFocused(true); }}
                    onFocus={() => setIsFocused(true)}
                    placeholder="Add a tag"
                    aria-label="Add a tag"
                    className="flex-1 rounded-lg border border-white/10 bg-gray-800 px-3 py-1.5 text-xs text-white placeholder-gray-500 focus:border-cyan-500/50 focus:outline-none"
                />
                <button
                    type="submit"
                    disabled={!draft.trim() || addTag.isPending}
                    aria-label="Save tag"
                    className="rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-2 py-1.5 text-cyan-300 hover:bg-cyan-500/20 disabled:opacity-40"
                >
                    <Plus size={14} />
                </button>
            </form>

            {isFocused && suggestions.length > 0 && (
                <ul className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-white/10 bg-gray-900 shadow-xl">
                    {suggestions.map((entry) => (
                        <li key={entry.tag}>
                            <button
                                type="button"
                                onClick={() => submit(entry.tag)}
                                className="flex w-full items-center justify-between px-3 py-1.5 text-left text-xs text-gray-300 hover:bg-white/5"
                            >
                                <span className="truncate">{entry.tag}</span>
                                <span className="ml-2 shrink-0 text-gray-500">{entry.count}</span>
                            </button>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
