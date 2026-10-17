import React, { useState } from 'react';
import { X, Sparkles, MapPin, Shield, BookOpen, User, Check, Plus, Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { useAdoptWorldbuilding } from '../../hooks/useStories';

const CATEGORY_ICONS = {
    location: MapPin,
    faction: Shield,
    lore: BookOpen,
    character: User,
};

const CATEGORY_COLORS = {
    location: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    faction: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
    lore: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
    character: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
};

export default function WorldDiscoveryDrawer({
    isOpen,
    onClose,
    discoveries = [],
    storyId,
    worldId,
    chapterTitle,
    error,
    onRetry,
}) {
    const adoptMutation = useAdoptWorldbuilding();
    const [adoptedNames, setAdoptedNames] = useState(new Set());
    const [adoptingName, setAdoptingName] = useState(null);

    if (!isOpen) return null;

    const handleAdopt = async (item) => {
        if (!storyId || adoptedNames.has(item.name)) return;
        setAdoptingName(item.name);
        try {
            await adoptMutation.mutateAsync({
                storyId,
                data: {
                    name: item.name,
                    category: item.category,
                    summary: item.summary,
                    tags: item.tags,
                    target_action: item.suggested_action,
                    world_id: worldId || undefined,
                },
            });
            setAdoptedNames((prev) => new Set([...prev, item.name]));
            toast.success(`Adopted "${item.name}" into World Vault!`);
        } catch (err) {
            toast.error(err?.message || `Failed to adopt "${item.name}"`);
        } finally {
            setAdoptingName(null);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in">
            <div className="w-full max-w-2xl bg-gray-900 border border-gray-700/60 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
                {/* Header */}
                <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800 bg-gray-900/80">
                    <div className="flex items-center gap-2.5">
                        <div className="p-2 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400">
                            <Sparkles size={18} />
                        </div>
                        <div>
                            <h3 className="text-base font-semibold text-gray-100 flex items-center gap-2">
                                World Vault Discoveries
                                <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-mono">
                                    {discoveries.length} found
                                </span>
                            </h3>
                            <p className="text-xs text-gray-400">
                                Novel locations, factions, and lore extracted from prose in {chapterTitle || 'this chapter'}
                            </p>
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
                        aria-label="Close"
                    >
                        <X size={18} />
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-5 space-y-3">
                    {error ? (
                        <div role="alert" className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-xs flex items-center justify-between">
                            <span>{error?.message || 'Failed to discover worldbuilding elements.'}</span>
                            {onRetry && (
                                <button
                                    onClick={onRetry}
                                    className="px-2.5 py-1 rounded bg-red-500/20 hover:bg-red-500/30 text-red-200 text-xs transition-colors"
                                >
                                    Retry
                                </button>
                            )}
                        </div>
                    ) : discoveries.length === 0 ? (
                        <div className="text-center py-10 space-y-2">
                            <Sparkles className="mx-auto text-gray-600 animate-pulse" size={32} />
                            <p className="text-sm text-gray-400">No new worldbuilding elements detected in this scene yet.</p>
                            <p className="text-xs text-gray-600">
                                As your story introduces new landmarks, factions, and relics, they will appear here for 1-click addition to the World Vault.
                            </p>
                        </div>
                    ) : (
                        discoveries.map((item) => {
                            const Icon = CATEGORY_ICONS[item.category] || BookOpen;
                            const colorClass = CATEGORY_COLORS[item.category] || CATEGORY_COLORS.lore;
                            const isAdopted = adoptedNames.has(item.name);
                            const isProcessing = adoptingName === item.name;

                            return (
                                <div
                                    key={item.name}
                                    className="p-3.5 rounded-xl border border-gray-800/80 bg-gray-800/30 hover:bg-gray-800/50 transition-all flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3"
                                >
                                    <div className="space-y-1 flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-3xs font-semibold uppercase tracking-wider border ${colorClass}`}>
                                                <Icon size={10} />
                                                {item.category}
                                            </span>
                                            <h4 className="text-sm font-semibold text-gray-200 truncate">{item.name}</h4>
                                        </div>
                                        <p className="text-xs text-gray-400 line-clamp-2 italic">
                                            "{item.summary}"
                                        </p>
                                        {item.tags?.length > 0 && (
                                            <div className="flex gap-1 flex-wrap pt-0.5">
                                                {item.tags.map((t) => (
                                                    <span key={t} className="text-3xs px-1.5 py-px rounded bg-gray-800 text-gray-500">
                                                        #{t}
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                    </div>

                                    <button
                                        onClick={() => handleAdopt(item)}
                                        disabled={isAdopted || isProcessing}
                                        className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${
                                            isAdopted
                                                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 cursor-default'
                                                : 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-sm hover:scale-105 active:scale-95'
                                        }`}
                                    >
                                        {isProcessing ? (
                                            <>
                                                <Loader2 size={13} className="animate-spin" />
                                                <span>Adding...</span>
                                            </>
                                        ) : isAdopted ? (
                                            <>
                                                <Check size={13} />
                                                <span>In Vault</span>
                                            </>
                                        ) : (
                                            <>
                                                <Plus size={13} />
                                                <span>Add to Vault</span>
                                            </>
                                        )}
                                    </button>
                                </div>
                            );
                        })
                    )}
                </div>

                {/* Footer */}
                <div className="px-5 py-3 border-t border-gray-800 bg-gray-900/80 flex items-center justify-between text-xs text-gray-500">
                    <span>Adopted items are vectorized with pgvector for instant semantic retrieval.</span>
                    <button
                        onClick={onClose}
                        className="px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 transition-colors"
                    >
                        Done
                    </button>
                </div>
            </div>
        </div>
    );
}
