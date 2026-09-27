import { useState } from 'react';
import { Filter, X } from 'lucide-react';

/**
 * Tag picker for the model lists.
 *
 * This is the one tag UX in the app. It was inline in the model manager's
 * Installed tab, which meant the in-generator picker (ModelSelector ->
 * ModelFilterBar) had no way to filter by tag at all — so a LoRA tagged for a
 * character was only findable from the one screen that happened to render
 * checkboxes. Both call sites now share this component rather than growing a
 * second design.
 *
 * Filtering is server-side: the selection is sent to `GET /api/files` as the
 * comma-separated `tags` query param, which the backend applies as AND across
 * the list. `availableTags` is whatever the caller has loaded so far, so a tag
 * only becomes selectable once a model carrying it has been seen — the panel
 * says so rather than the control vanishing, because a control that appears
 * and disappears mid-refresh is both jarring and unreachable.
 *
 * Read-only by design. It is a filter over a whole list, so it has no model to
 * attach a tag to or delete one from; the write side lives with the model
 * itself, in ModelDetailsModal. It can still *label* a tag's origin, because
 * "your tag" and "a tag a scraper wrote" are not the same thing to a user who
 * is trying to remember why a model is findable: `tagSources` maps a tag to
 * `'user'` or `'civitai'`, and a user tag is marked. A tag missing from the
 * map is marked nothing at all rather than guessed at — see the prop.
 */
export default function ModelTagFilter({
    availableTags = [],
    selectedTags = [],
    onSelectedTagsChange,
    tagSources = {},
}) {
    // Hover already reveals the panel, but a hover-only menu cannot be reached by
    // keyboard or touch, so click toggles it too.
    const [open, setOpen] = useState(false);

    const toggleTag = (tag) => {
        onSelectedTagsChange(
            selectedTags.includes(tag)
                ? selectedTags.filter(t => t !== tag)
                : [...selectedTags, tag]
        );
    };

    return (
        <div className="flex flex-col gap-2">
            <div className="relative group">
                <button
                    type="button"
                    onClick={() => setOpen(v => !v)}
                    aria-expanded={open}
                    aria-label={`Filter by tag, ${selectedTags.length} selected`}
                    className="flex items-center gap-2 px-5 py-3 bg-[#0B0E14]/80 border border-white/10 rounded-xl text-gray-300 hover:text-white hover:border-white/20 shadow-inner transition-all"
                >
                    <Filter size={20} />
                    <span className="font-bold text-2xs uppercase tracking-widest">
                        Tags ({selectedTags.length})
                    </span>
                </button>
                <div
                    className={`absolute right-0 mt-2 w-64 max-h-96 overflow-y-auto glass-panel border border-white/10 rounded-2xl shadow-2xl p-3 z-20 backdrop-blur-xl ${open ? 'block' : 'hidden group-hover:block'}`}
                >
                    {availableTags.length === 0 && (
                        <p className="p-2 text-xs text-gray-500">
                            No tags on the loaded models yet. Open a model's
                            details to give it a tag of your own.
                        </p>
                    )}
                    {availableTags.map(tag => (
                        <label key={tag} className="flex items-center gap-3 p-2 hover:bg-white/5 rounded-xl cursor-pointer transition-colors">
                            <input
                                type="checkbox"
                                checked={selectedTags.includes(tag)}
                                onChange={() => toggleTag(tag)}
                                className="rounded border-white/10 bg-black/40 text-blue-500 focus:ring-blue-500/50"
                            />
                            <span className="text-sm font-medium text-gray-300">{tag}</span>
                            {tagSources[tag] === 'user' && (
                                <span
                                    className="ml-auto text-2xs uppercase tracking-widest font-bold text-emerald-400/80"
                                    title="A tag you added. CivitAI tags cannot be removed — a resync replaces them."
                                >
                                    yours
                                </span>
                            )}
                        </label>
                    ))}
                </div>
            </div>

            {selectedTags.length > 0 && (
                <div className="flex flex-wrap gap-2">
                    {selectedTags.map(tag => (
                        <span key={tag} className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-500/20 text-blue-300 rounded-full text-xs font-bold border border-blue-500/30 shadow-inner">
                            {tag}
                            <button
                                type="button"
                                onClick={() => toggleTag(tag)}
                                className="hover:text-white transition-colors"
                                aria-label={`Remove tag ${tag}`}
                            >
                                <X size={14} />
                            </button>
                        </span>
                    ))}
                    <button
                        type="button"
                        onClick={() => onSelectedTagsChange([])}
                        className="text-xs font-bold text-gray-500 hover:text-gray-300 uppercase tracking-widest transition-colors"
                        aria-label="Clear all tags"
                    >
                        Clear all
                    </button>
                </div>
            )}
        </div>
    );
}
