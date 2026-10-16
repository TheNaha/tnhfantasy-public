import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Save, Trash2, Plus, Pencil } from 'lucide-react';
import toast from 'react-hot-toast';
import { useQueryClient } from '@tanstack/react-query';
import {
    useCreateLorebook,
    useUpdateLorebook,
    useDeleteLorebook,
    useLorebookEntries,
    useCreateEntry,
    useUpdateEntry,
    useDeleteEntry,
} from '../../hooks/useLorebooks';
import { useWorlds } from '../../hooks/useWorlds';
import { useConfirmation } from '../../store/confirmationStore';
import { useEscapeKey } from '../../hooks/useEscapeKey';
import { buildQueryKey, QUERY_KEYS } from '../../constants/queryKeys';

export function LorebookModal({ isOpen, onClose, lorebook }) {
    // Escape dismisses, matching every other dialog expectation.
    useEscapeKey(onClose, !!isOpen);

    const [form, setForm] = useState({ name: '', description: '', world_id: '' });
    const [entryForm, setEntryForm] = useState({ id: null, keys: '', content: '' });
    const [showEntryEditor, setShowEntryEditor] = useState(false);
    const [saving, setSaving] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const queryClient = useQueryClient();
    const { confirm } = useConfirmation();
    const createLorebook = useCreateLorebook();
    const updateLorebook = useUpdateLorebook();
    const deleteLorebook = useDeleteLorebook();
    const { data: worlds = [] } = useWorlds();
    const { data: entries = [] } = useLorebookEntries(isOpen && lorebook?.id ? lorebook.id : null);
    const createEntry = useCreateEntry();
    const updateEntry = useUpdateEntry();
    const deleteEntry = useDeleteEntry();

    useEffect(() => {
        if (isOpen) {
            setForm({
                name: lorebook?.name || '',
                description: lorebook?.description || '',
                world_id: lorebook?.world_id || '',
            });
            setEntryForm({ id: null, keys: '', content: '' });
            setShowEntryEditor(false);
        }
    }, [isOpen, lorebook]);

    if (!isOpen) return null;

    const handleSave = async () => {
        if (!form.name.trim()) {
            toast.error('Name is required');
            return;
        }
        const payload = {
            ...form,
            world_id: form.world_id || null,
        };
        setSaving(true);
        try {
            if (lorebook) {
                await updateLorebook.mutateAsync({ id: lorebook.id, ...payload });
                toast.success('Lorebook updated');
            } else {
                await createLorebook.mutateAsync(payload);
                toast.success('Lorebook created');
            }
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.LOREBOOKS) });
            onClose();
        } catch (e) {
            console.error(e);
            toast.error('Failed to save lorebook');
        } finally {
            setSaving(false);
        }
    };

    const handleSaveEntry = async () => {
        if (!lorebook?.id) return;
        if (!entryForm.content.trim()) {
            toast.error('Entry content is required');
            return;
        }
        const keys = entryForm.keys
            .split(',')
            .map(k => k.trim())
            .filter(Boolean);
        try {
            if (entryForm.id) {
                await updateEntry.mutateAsync({
                    lorebookId: lorebook.id,
                    id: entryForm.id,
                    keys,
                    content: entryForm.content.trim(),
                });
                toast.success('Entry updated');
            } else {
                await createEntry.mutateAsync({
                    lorebookId: lorebook.id,
                    keys,
                    content: entryForm.content.trim(),
                });
                toast.success('Entry added');
            }
            setEntryForm({ id: null, keys: '', content: '' });
            setShowEntryEditor(false);
        } catch (e) {
            console.error(e);
            toast.error('Failed to save entry');
        }
    };

    const handleDeleteEntry = async (entryId) => {
        if (!lorebook?.id) return;
        try {
            await deleteEntry.mutateAsync({ lorebookId: lorebook.id, id: entryId });
            toast.success('Entry removed');
        } catch (e) {
            console.error(e);
            toast.error('Failed to remove entry');
        }
    };

    const handleDelete = async () => {
        if (!lorebook) return;
        const ok = await confirm({
            title: 'Delete Lorebook',
            message: `Are you sure you want to delete "${lorebook.name}"? All entries will be removed and it will be detached from any chats or stories.`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        setDeleting(true);
        try {
            await deleteLorebook.mutateAsync(lorebook.id);
            toast.success('Lorebook deleted');
            onClose();
        } catch (e) {
            console.error(e);
            toast.error('Failed to delete lorebook');
        } finally {
            setDeleting(false);
        }
    };

    return (
        <AnimatePresence>
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                    onClick={onClose}
                />
                <motion.div
                    initial={{ opacity: 0, scale: 0.95, y: 20 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95, y: 20 }}
                    className="relative w-full max-w-2xl bg-gray-900 border border-gray-700 rounded-xl shadow-2xl flex flex-col max-h-full overflow-hidden"
                >
                    {/* Header */}
                    <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 bg-gray-900/50">
                        <h2 className="text-xl font-semibold text-gray-100">
                            {lorebook ? 'Edit Lorebook' : 'Create Lorebook'}
                        </h2>
                        <button onClick={onClose} aria-label={lorebook ? 'Close edit lorebook' : 'Close create lorebook'} className="p-2 text-gray-400 hover:text-white rounded-lg hover:bg-white/10 transition-colors">
                            <X size={20} />
                        </button>
                    </div>

                    {/* Content */}
                    <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
                        <div className="space-y-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-1.5">Name</label>
                                <input
                                    type="text"
                                    value={form.name}
                                    onChange={(e) => setForm(prev => ({ ...prev, name: e.target.value }))}
                                    className="w-full bg-black/40 border border-gray-700 rounded-lg px-4 py-2.5 text-gray-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all"
                                    placeholder="Lorebook Name"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-1.5">World (Optional)</label>
                                <select
                                    value={form.world_id || ''}
                                    onChange={(e) => setForm(prev => ({ ...prev, world_id: e.target.value }))}
                                    aria-label="Lorebook World"
                                    className="w-full bg-black/40 border border-gray-700 rounded-lg px-4 py-2.5 text-gray-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all"
                                >
                                    <option value="">No World (Global)</option>
                                    {worlds.map(w => (
                                        <option key={w.id} value={w.id}>{w.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-1.5">Description</label>
                                <textarea
                                    value={form.description}
                                    onChange={(e) => setForm(prev => ({ ...prev, description: e.target.value }))}
                                    className="w-full h-24 bg-black/40 border border-gray-700 rounded-lg px-4 py-3 text-gray-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all resize-none custom-scrollbar"
                                    placeholder="Description of this lorebook"
                                />
                            </div>

                            {lorebook?.id && (
                                <div className="pt-4 border-t border-gray-800 space-y-3">
                                    <div className="flex items-center justify-between">
                                        <h3 className="text-sm font-medium text-gray-300">
                                            Entries ({entries.length})
                                        </h3>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setEntryForm({ id: null, keys: '', content: '' });
                                                setShowEntryEditor(true);
                                            }}
                                            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-indigo-400 hover:text-indigo-300 bg-indigo-500/10 hover:bg-indigo-500/20 rounded-md transition-colors"
                                        >
                                            <Plus size={14} /> Add Entry
                                        </button>
                                    </div>

                                    {showEntryEditor && (
                                        <div className="p-3 bg-black/40 border border-gray-700 rounded-lg space-y-2.5">
                                            <input
                                                type="text"
                                                value={entryForm.keys}
                                                onChange={(e) => setEntryForm(prev => ({ ...prev, keys: e.target.value }))}
                                                placeholder="Trigger keys (comma-separated)"
                                                className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-300 focus:outline-none focus:border-indigo-500"
                                            />
                                            <textarea
                                                value={entryForm.content}
                                                onChange={(e) => setEntryForm(prev => ({ ...prev, content: e.target.value }))}
                                                placeholder="Lore entry content..."
                                                className="w-full h-24 bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-indigo-500 resize-none"
                                            />
                                            <div className="flex justify-end gap-2">
                                                <button
                                                    type="button"
                                                    onClick={() => setShowEntryEditor(false)}
                                                    className="px-2.5 py-1 text-xs text-gray-400 hover:text-white"
                                                >
                                                    Cancel
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={handleSaveEntry}
                                                    className="px-3 py-1 text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white rounded transition-colors"
                                                >
                                                    {entryForm.id ? 'Update Entry' : 'Save Entry'}
                                                </button>
                                            </div>
                                        </div>
                                    )}

                                    <div className="space-y-2 max-h-48 overflow-y-auto custom-scrollbar">
                                        {entries.map(entry => {
                                            const entryLabel = (entry.keys || []).join(', ') || entry.content?.slice(0, 30) || entry.id;
                                            return (
                                                <div key={entry.id} className="flex items-start justify-between gap-2 p-2.5 bg-black/30 border border-gray-800 rounded-lg">
                                                    <div className="min-w-0 flex-1">
                                                        {entry.keys?.length > 0 && (
                                                            <div className="text-[11px] font-semibold text-indigo-400 truncate">
                                                                {entry.keys.join(', ')}
                                                            </div>
                                                        )}
                                                        <div className="text-xs text-gray-400 line-clamp-2 mt-0.5">{entry.content}</div>
                                                    </div>
                                                    <div className="flex items-center gap-1 shrink-0">
                                                        <button
                                                            type="button"
                                                            onClick={() => {
                                                                setEntryForm({
                                                                    id: entry.id,
                                                                    keys: (entry.keys || []).join(', '),
                                                                    content: entry.content || '',
                                                                });
                                                                setShowEntryEditor(true);
                                                            }}
                                                            aria-label={`Edit entry ${entryLabel}`}
                                                            className="p-1 text-gray-400 hover:text-white rounded"
                                                        >
                                                            <Pencil size={13} />
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={() => handleDeleteEntry(entry.id)}
                                                            aria-label={`Delete entry ${entryLabel}`}
                                                            className="p-1 text-gray-400 hover:text-red-400 rounded"
                                                        >
                                                            <Trash2 size={13} />
                                                        </button>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                        {entries.length === 0 && !showEntryEditor && (
                                            <p className="text-xs text-gray-500 italic">No entries yet. Click &ldquo;Add Entry&rdquo; to add world lore.</p>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Footer */}
                    <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-gray-800 bg-gray-900/50">
                        {lorebook ? (
                            <button
                                onClick={handleDelete}
                                disabled={deleting}
                                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <Trash2 size={16} />
                                {deleting ? 'Deleting...' : 'Delete'}
                            </button>
                        ) : <div />}
                        <div className="flex items-center gap-3">
                            <button
                                onClick={onClose}
                                className="px-4 py-2 text-sm font-medium text-gray-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleSave}
                                disabled={saving}
                                className="flex items-center gap-2 px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors shadow-lg shadow-indigo-500/20"
                            >
                                <Save size={16} />
                                {saving ? 'Saving...' : lorebook ? 'Save Changes' : 'Create Lorebook'}
                            </button>
                        </div>
                    </div>
                </motion.div>
            </div>
        </AnimatePresence>
    );
}