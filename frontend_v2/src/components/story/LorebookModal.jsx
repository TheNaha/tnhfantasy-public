import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Save, Trash2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { useQueryClient } from '@tanstack/react-query';
import { useCreateLorebook, useUpdateLorebook, useDeleteLorebook } from '../../hooks/useLorebooks';
import { useConfirmation } from '../../store/confirmationStore';
import { useEscapeKey } from '../../hooks/useEscapeKey';
import { buildQueryKey, QUERY_KEYS } from '../../constants/queryKeys';

export function LorebookModal({ isOpen, onClose, lorebook }) {
    // Escape dismisses, matching every other dialog expectation.
    useEscapeKey(onClose, !!isOpen);

    const [form, setForm] = useState({ name: '', description: '' });
    const [saving, setSaving] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const queryClient = useQueryClient();
    const { confirm } = useConfirmation();
    const createLorebook = useCreateLorebook();
    const updateLorebook = useUpdateLorebook();
    const deleteLorebook = useDeleteLorebook();

    useEffect(() => {
        if (isOpen) {
            setForm({
                name: lorebook?.name || '',
                description: lorebook?.description || '',
            });
        }
    }, [isOpen, lorebook]);

    if (!isOpen) return null;

    const handleSave = async () => {
        if (!form.name.trim()) {
            toast.error('Name is required');
            return;
        }
        setSaving(true);
        try {
            if (lorebook) {
                await updateLorebook.mutateAsync({ id: lorebook.id, ...form });
                toast.success('Lorebook updated');
            } else {
                await createLorebook.mutateAsync(form);
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
                                <label className="block text-sm font-medium text-gray-400 mb-1.5">Description</label>
                                <textarea
                                    value={form.description}
                                    onChange={(e) => setForm(prev => ({ ...prev, description: e.target.value }))}
                                    className="w-full h-32 bg-black/40 border border-gray-700 rounded-lg px-4 py-3 text-gray-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all resize-none custom-scrollbar"
                                    placeholder="Description of this lorebook"
                                />
                            </div>
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