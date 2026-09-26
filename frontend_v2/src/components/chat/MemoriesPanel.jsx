import React, { useState } from 'react';
import { Brain, Plus, Trash2, Search, X, Loader2, Pencil } from 'lucide-react';
import toast from 'react-hot-toast';
import {
    useCharacterMemories,
    useCreateMemory,
    useUpdateMemory,
    useDeleteMemory,
    useSearchMemories,
} from '../../hooks/useMemories';
import { useDebounce } from '../../hooks/useDebounce';
import EmptyState from '../EmptyState';
import { useConfirmation } from '../../store/confirmationStore';

const SEARCH_MIN_CHARS = 2;
const SEARCH_DEBOUNCE_MS = 300;

// Importance 1-3 = red, 4-6 = yellow, 7-10 = green
function ImportanceDot({ value }) {
    const color =
        value >= 7
            ? 'bg-emerald-400'
            : value >= 4
            ? 'bg-yellow-400'
            : 'bg-red-400';
    return (
        <span
            className={`inline-flex items-center justify-center w-5 h-5 rounded-full text-2xs font-bold text-gray-900 shrink-0 ${color}`}
            title={`Importance: ${value}/10`}
        >
            {value}
        </span>
    );
}

function MemoryTag({ label }) {
    return (
        <span className="px-1.5 py-0.5 text-xs bg-indigo-500/15 text-indigo-300 rounded border border-indigo-500/25 leading-none">
            {label}
        </span>
    );
}

function MemorySkeleton() {
    return (
        <div className="space-y-2 animate-pulse">
            {[...Array(3)].map((_, i) => (
                <div
                    key={i}
                    className="flex gap-3 p-3 bg-gray-800/40 rounded-lg border border-white/5"
                >
                    <div className="w-5 h-5 rounded-full bg-gray-700 shrink-0 mt-0.5" />
                    <div className="flex-1 space-y-2">
                        <div className="h-3 bg-gray-700 rounded w-4/5" />
                        <div className="h-3 bg-gray-700 rounded w-2/3" />
                        <div className="flex gap-1 mt-1">
                            <div className="h-4 w-12 bg-gray-700 rounded" />
                            <div className="h-4 w-10 bg-gray-700 rounded" />
                        </div>
                    </div>
                </div>
            ))}
        </div>
    );
}

/**
 * Every piece of state below (search, the add-form draft, and the in-progress
 * edit, which holds a memory id) belongs to exactly one character. Without a
 * reset on switch, chat A / character X → edit a memory → chat B / character Y
 * shows X's memory under Y's heading, and Save PUTs X's row while invalidating
 * Y's cache. The keyed wrapper below is what guarantees that: React discards
 * the whole stateful subtree on a character change, at every call site
 * (ChatContextPanel and the unkeyed one in pages/Characters.jsx).
 */
export default function MemoriesPanel({ characterId }) {
    return <MemoriesPanelBody key={characterId} characterId={characterId} />;
}

function MemoriesPanelBody({ characterId }) {
    const [searchQuery, setSearchQuery] = useState('');
    const [showAddForm, setShowAddForm] = useState(false);
    const [newContent, setNewContent] = useState('');
    const [newImportance, setNewImportance] = useState(5);
    const [newTags, setNewTags] = useState('');

    const { data: memories = [], isLoading } = useCharacterMemories(characterId);
    // One request per keystroke was the old behaviour; the debounce means the
    // search only runs once typing settles.
    const debouncedSearchQuery = useDebounce(searchQuery, SEARCH_DEBOUNCE_MS);
    const settledQuery = debouncedSearchQuery.trim();
    const { data: searchResults, isFetching: isSearchFetching } = useSearchMemories(characterId, settledQuery);
    const createMutation = useCreateMemory();
    const updateMutation = useUpdateMemory();
    const deleteMutation = useDeleteMemory();
    const { confirm } = useConfirmation();
    const [editingMemory, setEditingMemory] = useState(null);
    const [editContent, setEditContent] = useState('');
    const [editImportance, setEditImportance] = useState(5);
    const [editTags, setEditTags] = useState('');

    const isSearching = settledQuery.length >= SEARCH_MIN_CHARS;
    // True from the first qualifying keystroke until its results have landed:
    // during the debounce window the query has not run yet, and while it is in
    // flight `searchResults` is undefined. Either way the list must not fall
    // through to the "No matches found" empty state, which previously replaced
    // the whole list on every keystroke.
    const isAwaitingResults = searchQuery.trim().length >= SEARCH_MIN_CHARS && (!isSearching || isSearchFetching);
    const displayed = isSearching ? (searchResults ?? []) : memories;

    const handleAdd = async () => {
        if (!newContent.trim()) return;
        const tags = newTags
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean);
        try {
            await createMutation.mutateAsync({
                character_id: characterId,
                content: newContent.trim(),
                importance: newImportance,
                tags,
            });
            setNewContent('');
            setNewTags('');
            setNewImportance(5);
            setShowAddForm(false);
            toast.success('Memory added');
        } catch {
            toast.error('Failed to add memory');
        }
    };

    const handleDelete = async (memory) => {
        const ok = await confirm({
            title: 'Delete Memory',
            message: 'Remove this memory permanently?',
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            await deleteMutation.mutateAsync({ id: memory.id, characterId });
            toast.success('Memory deleted');
        } catch {
            toast.error('Failed to delete memory');
        }
    };

    const startEdit = (memory) => {
        setEditingMemory(memory);
        setEditContent(memory.content);
        setEditImportance(memory.importance ?? 5);
        setEditTags((memory.tags || []).join(', '));
    };

    const cancelEdit = () => {
        setEditingMemory(null);
        setEditContent('');
        setEditImportance(5);
        setEditTags('');
    };

    const handleSaveEdit = async () => {
        if (!editingMemory || !editContent.trim()) return;
        const tags = editTags
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean);
        try {
            await updateMutation.mutateAsync({
                id: editingMemory.id,
                characterId,
                content: editContent.trim(),
                importance: editImportance,
                tags,
            });
            toast.success('Memory updated');
            cancelEdit();
        } catch {
            toast.error('Failed to update memory');
        }
    };

    const importanceColor =
        newImportance >= 7
            ? 'text-emerald-400'
            : newImportance >= 4
            ? 'text-yellow-400'
            : 'text-red-400';

    return (
        <div className="flex flex-col gap-3">
            {/* ── Header row ─────────────────────────────────────── */}
            <div className="flex items-center gap-2">
                {/* Search */}
                <div className="relative flex-1">
                    <Search
                        size={13}
                        className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none"
                    />
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Semantic search…"
                        className="w-full bg-gray-800/60 border border-white/5 text-xs rounded-lg pl-7 pr-7 py-1.5 text-gray-300 placeholder-gray-600 focus:outline-none focus:border-blue-500/40"
                    />
                    {searchQuery && (
                        <button
                            type="button"
                            onClick={() => setSearchQuery('')}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 transition-colors"
                        >
                            <X size={12} />
                        </button>
                    )}
                </div>

                {/* Add button */}
                <button
                    type="button"
                    onClick={() => setShowAddForm((v) => !v)}
                    className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-colors shrink-0 ${
                        showAddForm
                            ? 'bg-blue-500/20 text-blue-300 border-blue-500/30 hover:bg-blue-500/30'
                            : 'bg-white/5 text-gray-400 border-white/5 hover:bg-white/10 hover:text-white'
                    }`}
                    title={showAddForm ? 'Cancel' : 'Add memory'}
                >
                    {showAddForm ? <X size={13} /> : <Plus size={13} />}
                    {showAddForm ? 'Cancel' : 'Add'}
                </button>
            </div>

            {/* ── Add form ────────────────────────────────────────── */}
            {showAddForm && (
                <div className="glass-panel rounded-xl border border-blue-500/20 bg-blue-500/5 p-3 space-y-2.5">
                    <textarea
                        value={newContent}
                        onChange={(e) => setNewContent(e.target.value)}
                        placeholder="Memory content…"
                        rows={3}
                        className="w-full bg-gray-800/60 border border-white/5 text-xs rounded-lg px-3 py-2 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/40 resize-none"
                        autoFocus
                    />

                    {/* Importance slider */}
                    <div>
                        <div className="flex items-center justify-between mb-1">
                            <label className="text-xs text-gray-500 uppercase tracking-wider font-semibold">
                                Importance
                            </label>
                            <span className={`text-xs font-bold ${importanceColor}`}>
                                {newImportance}/10
                            </span>
                        </div>
                        <input
                            type="range"
                            min={1}
                            max={10}
                            step={1}
                            value={newImportance}
                            onChange={(e) => setNewImportance(Number(e.target.value))}
                            className="w-full accent-blue-500"
                        />
                        <div className="flex justify-between text-2xs text-gray-600 mt-0.5">
                            <span>Low</span>
                            <span>Medium</span>
                            <span>High</span>
                        </div>
                    </div>

                    {/* Tags */}
                    <div>
                        <label className="text-xs text-gray-500 uppercase tracking-wider font-semibold">
                            Tags (comma-separated)
                        </label>
                        <input
                            type="text"
                            value={newTags}
                            onChange={(e) => setNewTags(e.target.value)}
                            placeholder="e.g. backstory, secret, combat"
                            className="mt-1 w-full bg-gray-800/60 border border-white/5 text-xs rounded-lg px-2.5 py-1.5 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/40"
                        />
                    </div>

                    <button
                        type="button"
                        onClick={handleAdd}
                        disabled={!newContent.trim() || createMutation.isPending}
                        className="w-full flex items-center justify-center gap-1.5 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-medium rounded-lg transition-colors"
                    >
                        {createMutation.isPending ? (
                            <Loader2 size={12} className="animate-spin" />
                        ) : (
                            <Brain size={12} />
                        )}
                        Save Memory
                    </button>
                </div>
            )}

            {/* ── Edit form ───────────────────────────────────────── */}
            {editingMemory && (
                <div className="glass-panel rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-3 space-y-2.5">
                    <div className="flex items-center justify-between">
                        <label className="text-xs text-indigo-300 uppercase tracking-wider font-semibold">
                            Editing memory
                        </label>
                        <button
                            type="button"
                            onClick={cancelEdit}
                            className="p-1 min-w-6 min-h-6 inline-flex items-center justify-center text-gray-500 hover:text-gray-300 rounded transition-colors"
                            title="Cancel edit"
                        >
                            <X size={12} />
                        </button>
                    </div>
                    <textarea
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                        placeholder="Memory content…"
                        rows={3}
                        className="w-full bg-gray-800/60 border border-white/5 text-xs rounded-lg px-3 py-2 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500/40 resize-none"
                        autoFocus
                    />
                    <div>
                        <div className="flex items-center justify-between mb-1">
                            <label className="text-xs text-gray-500 uppercase tracking-wider font-semibold">
                                Importance
                            </label>
                            <span className={`text-xs font-bold ${
                                editImportance >= 7
                                    ? 'text-emerald-400'
                                    : editImportance >= 4
                                    ? 'text-yellow-400'
                                    : 'text-red-400'
                            }`}>
                                {editImportance}/10
                            </span>
                        </div>
                        <input
                            type="range"
                            min={1}
                            max={10}
                            step={1}
                            value={editImportance}
                            onChange={(e) => setEditImportance(Number(e.target.value))}
                            className="w-full accent-indigo-500"
                        />
                    </div>
                    <input
                        type="text"
                        value={editTags}
                        onChange={(e) => setEditTags(e.target.value)}
                        placeholder="Tags (comma-separated)"
                        className="w-full bg-gray-800/60 border border-white/5 text-xs rounded-lg px-2.5 py-1.5 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500/40"
                    />
                    <button
                        type="button"
                        onClick={handleSaveEdit}
                        disabled={!editContent.trim() || updateMutation.isPending}
                        className="w-full flex items-center justify-center gap-1.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-medium rounded-lg transition-colors"
                    >
                        {updateMutation.isPending ? (
                            <Loader2 size={12} className="animate-spin" />
                        ) : (
                            <Pencil size={12} />
                        )}
                        Save Changes
                    </button>
                </div>
            )}

            {/* ── Memory list ─────────────────────────────────────── */}
            {isLoading || isAwaitingResults ? (
                <MemorySkeleton />
            ) : displayed.length === 0 ? (
                <div className="py-6">
                    <EmptyState
                        type="collection"
                        icon={Brain}
                        title={isSearching ? 'No matches found' : 'No memories yet'}
                        description={
                            isSearching
                                ? `No memories matched "${searchQuery}".`
                                : 'Add the first memory for this character.'
                        }
                        primaryLabel={isSearching ? 'Clear search' : undefined}
                        primaryAction={isSearching ? () => setSearchQuery('') : undefined}
                    />
                </div>
            ) : (
                <div className="space-y-2">
                    {isSearching && (
                        <p className="text-xs text-gray-500 px-1">
                            {displayed.length} semantic match{displayed.length !== 1 ? 'es' : ''} for &ldquo;{settledQuery}&rdquo;
                        </p>
                    )}
                    {displayed.map((memory) => (
                        <div
                            key={memory.id}
                            className="group flex gap-3 p-3 bg-gray-800/40 hover:bg-gray-800/60 rounded-lg border border-white/5 hover:border-white/10 transition-all"
                        >
                            {/* Importance dot */}
                            <div className="mt-0.5">
                                <ImportanceDot value={memory.importance ?? 5} />
                            </div>

                            {/* Content + meta */}
                            <div className="flex-1 min-w-0 space-y-1.5">
                                <p className="text-xs text-gray-200 leading-relaxed whitespace-pre-wrap break-words">
                                    {memory.content}
                                </p>

                                {/* Tags */}
                                {memory.tags?.length > 0 && (
                                    <div className="flex flex-wrap gap-1">
                                        {memory.tags.map((tag) => (
                                            <MemoryTag key={tag} label={tag} />
                                        ))}
                                    </div>
                                )}

                                {/* Timestamps */}
                                <p className="text-2xs text-gray-600">
                                    {memory.created_at
                                        ? new Date(memory.created_at).toLocaleDateString(undefined, {
                                              month: 'short',
                                              day: 'numeric',
                                              year: 'numeric',
                                          })
                                        : ''}
                                    {memory.last_accessed_at && (
                                        <span className="ml-2 text-gray-700">
                                            · accessed {new Date(memory.last_accessed_at).toLocaleDateString()}
                                        </span>
                                    )}
                                </p>
                            </div>

                            {/* Actions */}
                            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all shrink-0 self-start mt-0.5">
                                <button
                                    type="button"
                                    onClick={() => startEdit(memory)}
                                    className="p-1 min-w-6 min-h-6 inline-flex items-center justify-center text-gray-400 hover:text-indigo-400 rounded transition-colors"
                                    title="Edit memory"
                                >
                                    <Pencil size={13} />
                                </button>
                                <button
                                    type="button"
                                    onClick={() => handleDelete(memory)}
                                    disabled={deleteMutation.isPending}
                                    className="p-1 min-w-6 min-h-6 inline-flex items-center justify-center text-red-500/70 hover:text-red-400 transition-all rounded"
                                    title="Delete memory"
                                >
                                    <Trash2 size={13} />
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Footer count — hidden as soon as a search is typed, since the
                list above is showing search results (or the skeleton) then */}
            {!searchQuery.trim() && memories.length > 0 && (
                <p className="text-xs text-gray-600 text-right px-1">
                    {memories.length} memor{memories.length !== 1 ? 'ies' : 'y'}
                </p>
            )}
        </div>
    );
}
