import React, { useState, useMemo, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Edit3, Trash2, BookOpen, Search, RefreshCw, X, Save, ChevronRight, Key, FileText, Upload, Download } from 'lucide-react';
import toast from 'react-hot-toast';
import {
    useLorebooks,
    useCreateLorebook,
    useUpdateLorebook,
    useDeleteLorebook,
    useLorebookEntries,
    useCreateEntry,
    useUpdateEntry,
    useDeleteEntry,
    useSearchEntries,
    useReindexLorebook,
    useImportLorebookEntries,
    useBulkDeleteEntries,
} from '../hooks/useLorebooks';
import EmptyState from '../components/EmptyState';
import { useConfirmation } from '../store/confirmationStore';
import RoleplayPageShell from '../components/RoleplayPageShell';

export default function Lorebooks() {
    const [searchQuery, setSearchQuery] = useState('');
    const [showForm, setShowForm] = useState(false);
    const [editingId, setEditingId] = useState(null);
    const [form, setForm] = useState({ name: '', description: '' });
    const [activeLorebookId, setActiveLorebookId] = useState(null);

    const { data: lorebooks = [], isLoading } = useLorebooks();
    const createMutation = useCreateLorebook();
    const updateMutation = useUpdateLorebook();
    const deleteMutation = useDeleteLorebook();
    const { confirm } = useConfirmation();

    const filtered = useMemo(() => {
        if (!searchQuery.trim()) return lorebooks;
        const q = searchQuery.toLowerCase();
        return lorebooks.filter(lb =>
            lb.name?.toLowerCase().includes(q) ||
            (lb.description && lb.description.toLowerCase().includes(q))
        );
    }, [lorebooks, searchQuery]);

    const activeLorebook = lorebooks.find(lb => lb.id === activeLorebookId) || null;

    const resetForm = () => {
        setForm({ name: '', description: '' });
        setEditingId(null);
        setShowForm(false);
    };

    const handleSave = async () => {
        if (!form.name.trim()) {
            toast.error('Name is required');
            return;
        }
        try {
            if (editingId) {
                await updateMutation.mutateAsync({ id: editingId, ...form, name: form.name.trim() });
                toast.success('Lorebook updated');
            } else {
                await createMutation.mutateAsync({ ...form, name: form.name.trim() });
                toast.success('Lorebook created');
            }
            resetForm();
        } catch {
            toast.error('Failed to save lorebook');
        }
    };

    const handleEdit = (lb) => {
        setEditingId(lb.id);
        setForm({ name: lb.name || '', description: lb.description || '' });
        setShowForm(true);
    };

    const handleDelete = async (lb) => {
        const ok = await confirm({
            title: 'Delete Lorebook',
            message: `Are you sure you want to delete "${lb.name}" and all its entries?`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            await deleteMutation.mutateAsync(lb.id);
            if (activeLorebookId === lb.id) setActiveLorebookId(null);
            toast.success('Lorebook deleted');
        } catch {
            toast.error('Failed to delete lorebook');
        }
    };

    return (
        <RoleplayPageShell
            title="Lorebooks"
            description="Organize world knowledge into searchable entries."
            icon={BookOpen}
            actions={
                <button
                    onClick={() => { resetForm(); setShowForm(true); }}
                    className="flex items-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 font-medium text-slate-950 transition hover:bg-cyan-400"
                >
                    <Plus size={16} /> New Lorebook
                </button>
            }
        >

            <div className="mb-6">
                <div className="relative max-w-md">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search lorebooks..."
                        className="w-full pl-10 pr-4 py-2.5 bg-gray-800/60 border border-white/10 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                    />
                </div>
            </div>

            {isLoading ? (
                <div className="space-y-3">
                    {[1, 2, 3].map(i => (
                        <div key={i} className="bg-gray-900 border border-gray-700 rounded-xl p-4 animate-pulse">
                            <div className="h-5 bg-gray-700 rounded w-1/4 mb-2" />
                            <div className="h-4 bg-gray-700 rounded w-2/3" />
                        </div>
                    ))}
                </div>
            ) : filtered.length === 0 ? (
                <EmptyState
                    icon={BookOpen}
                    title="No lorebooks yet"
                    description="Create a lorebook to store world facts, character backgrounds, and setting details."
                    primaryLabel="New Lorebook"
                    onAction={() => { resetForm(); setShowForm(true); }}
                />
            ) : (
                <div className="space-y-3">
                    {filtered.map((lb) => (
                        <motion.div
                            key={lb.id}
                            layout
                            className="bg-gray-900 border border-gray-700 rounded-xl p-4 flex items-center justify-between group"
                        >
                            <div className="flex-1 min-w-0">
                                <h3 className="font-medium text-white truncate">{lb.name}</h3>
                                {lb.description && (
                                    <p className="text-sm text-gray-400 mt-0.5 line-clamp-2">{lb.description}</p>
                                )}
                            </div>
                            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                                <button onClick={() => setActiveLorebookId(lb.id)} className="p-1 text-gray-400 hover:text-blue-400 rounded" title="Manage entries">
                                    <ChevronRight size={14} />
                                </button>
                                <button
                                    onClick={() => {
                                        const a = document.createElement('a');
                                        a.href = `/api/v2/lorebooks/${lb.id}/export`;
                                        a.download = `${(lb.name || 'lorebook').replace(/[^a-z0-9_-]+/gi, '_')}.json`;
                                        document.body.appendChild(a);
                                        a.click();
                                        a.remove();
                                    }}
                                    className="p-1 text-gray-400 hover:text-white rounded"
                                    title="Export as SillyTavern world-book JSON"
                                >
                                    <Download size={14} />
                                </button>
                                <button onClick={() => handleEdit(lb)} className="p-1 text-gray-400 hover:text-white rounded" title="Edit">
                                    <Edit3 size={14} />
                                </button>
                                <button onClick={() => handleDelete(lb)} className="p-1 text-gray-400 hover:text-red-400 rounded" title="Delete">
                                    <Trash2 size={14} />
                                </button>
                            </div>
                        </motion.div>
                    ))}
                </div>
            )}

            <AnimatePresence>
                {showForm && (
                    <LorebookFormModal
                        editingId={editingId}
                        form={form}
                        setForm={setForm}
                        onSave={handleSave}
                        onClose={resetForm}
                        isSubmitting={createMutation.isPending || updateMutation.isPending}
                    />
                )}
            </AnimatePresence>

            <AnimatePresence>
                {activeLorebook && (
                    <EntryManagerModal
                        lorebook={activeLorebook}
                        onClose={() => setActiveLorebookId(null)}
                    />
                )}
            </AnimatePresence>
        </RoleplayPageShell>
    );
}

function LorebookFormModal({ editingId, form, setForm, onSave, onClose, isSubmitting }) {
    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4 overflow-y-auto"
            onClick={(e) => e.target === e.currentTarget && onClose()}
        >
            <motion.div
                initial={{ opacity: 0, scale: 0.95, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 10 }}
                className="bg-gray-900 border border-white/10 rounded-2xl p-6 w-full max-w-lg shadow-2xl max-h-[85vh] overflow-y-auto"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">
                        {editingId ? 'Edit Lorebook' : 'New Lorebook'}
                    </h2>
                    <button onClick={onClose} className="text-gray-400 hover:text-white">
                        <X size={20} />
                    </button>
                </div>
                <div className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium text-gray-300 mb-1">Name*</label>
                        <input
                            type="text"
                            className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                            value={form.name || ''}
                            onChange={(e) => setForm(f => ({ ...f, name: e.target.value }))}
                            placeholder="Lorebook name"
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-gray-300 mb-1">Description</label>
                        <textarea
                            className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                            value={form.description || ''}
                            onChange={(e) => setForm(f => ({ ...f, description: e.target.value }))}
                            placeholder="What does this lorebook cover?"
                            rows={3}
                        />
                    </div>
                </div>
                <div className="flex gap-2 justify-end mt-4">
                    <button onClick={onClose} className="px-4 py-2 text-gray-400 hover:text-white transition-colors">
                        Cancel
                    </button>
                    <button
                        onClick={onSave}
                        disabled={isSubmitting}
                        className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
                    >
                        {editingId ? 'Update' : 'Create'}
                    </button>
                </div>
            </motion.div>
        </motion.div>
    );
}

function EntryManagerModal({ lorebook, onClose }) {
    const [showAdd, setShowAdd] = useState(false);
    const [editingEntry, setEditingEntry] = useState(null);
    const [entryForm, setEntryForm] = useState({ keys: '', content: '' });
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedIds, setSelectedIds] = useState(new Set());
    const fileInputRef = useRef(null);

    const { data: entries = [], isLoading } = useLorebookEntries(lorebook.id);
    const createEntry = useCreateEntry();
    const updateEntry = useUpdateEntry();
    const deleteEntry = useDeleteEntry();
    const searchMutation = useSearchEntries();
    const reindexMutation = useReindexLorebook();
    const importEntries = useImportLorebookEntries();
    const bulkDeleteEntries = useBulkDeleteEntries();
    const { confirm } = useConfirmation();

    const isSearching = searchQuery.trim().length >= 2;
    const searchResults = searchMutation.data;
    const displayed = isSearching && searchResults ? searchResults : entries;

    const resetEntryForm = () => {
        setEntryForm({ keys: '', content: '' });
        setEditingEntry(null);
        setShowAdd(false);
    };

    const openEdit = (entry) => {
        setEditingEntry(entry);
        setEntryForm({
            keys: (entry.keys || []).join(', '),
            content: entry.content || '',
        });
        setShowAdd(true);
    };

    const handleSaveEntry = async () => {
        if (!entryForm.content.trim()) {
            return toast.error('Entry content is required');
        }
        const payload = {
            keys: entryForm.keys.split(',').map(k => k.trim()).filter(Boolean),
            content: entryForm.content.trim(),
        };
        try {
            if (editingEntry) {
                await updateEntry.mutateAsync({ lorebookId: lorebook.id, id: editingEntry.id, ...payload });
                toast.success('Entry updated');
            } else {
                await createEntry.mutateAsync({ lorebookId: lorebook.id, ...payload });
                toast.success('Entry added');
            }
            resetEntryForm();
        } catch {
            toast.error('Failed to save entry');
        }
    };

    const handleDeleteEntry = async (entry) => {
        const ok = await confirm({
            title: 'Delete Entry',
            message: 'Remove this lorebook entry?',
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            await deleteEntry.mutateAsync({ lorebookId: lorebook.id, id: entry.id });
            toast.success('Entry deleted');
        } catch {
            toast.error('Failed to delete entry');
        }
    };

    const handleSearch = () => {
        if (isSearching) {
            searchMutation.mutate({ lorebookId: lorebook.id, q: searchQuery.trim(), limit: 10 });
        }
    };

    const handleReindex = () => {
        reindexMutation.mutate(lorebook.id, {
            onSuccess: (data) => toast.success(`Reindexed ${data.reindexed} entries`),
            onError: () => toast.error('Reindex failed'),
        });
    };

    const handleImportFile = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;
        let payload;
        try {
            payload = JSON.parse(await file.text());
        } catch {
            toast.error('Not a valid JSON file');
            return;
        }
        toast.promise(
            importEntries.mutateAsync({ lorebookId: lorebook.id, payload }),
            {
                loading: 'Importing entries...',
                success: (data) => `Imported ${data?.imported ?? 0} entries`,
                error: (err) => err?.response?.data?.error || 'Import failed',
            }
        );
    };

    const toggleSelected = (entryId) => {
        setSelectedIds(prev => {
            const next = new Set(prev);
            next.has(entryId) ? next.delete(entryId) : next.add(entryId);
            return next;
        });
    };

    const handleBulkDelete = async () => {
        const count = selectedIds.size;
        if (count === 0) return;
        const ok = await confirm({
            title: 'Delete Entries',
            message: `Delete ${count} selected ${count === 1 ? 'entry' : 'entries'}?`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            const data = await bulkDeleteEntries.mutateAsync({ lorebookId: lorebook.id, entryIds: [...selectedIds] });
            setSelectedIds(new Set());
            toast.success(`Deleted ${data?.deleted ?? count} entries`);
        } catch {
            toast.error('Bulk delete failed');
        }
    };

    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4 overflow-y-auto"
            onClick={(e) => e.target === e.currentTarget && onClose()}
        >
            <motion.div
                initial={{ opacity: 0, scale: 0.95, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 10 }}
                className="bg-gray-900 border border-white/10 rounded-2xl w-full max-w-2xl shadow-2xl max-h-[85vh] flex flex-col overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
                    <div className="min-w-0">
                        <h2 className="text-lg font-semibold text-white truncate">{lorebook.name} — Entries</h2>
                        {lorebook.description && (
                            <p className="text-xs text-gray-500 truncate">{lorebook.description}</p>
                        )}
                    </div>
                    <button onClick={onClose} className="text-gray-400 hover:text-white shrink-0">
                        <X size={20} />
                    </button>
                </div>

                <div className="px-6 py-3 border-b border-gray-800 flex items-center gap-2">
                    <div className="relative flex-1">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" size={14} />
                        <input
                            type="text"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                            placeholder="Semantic search entries..."
                            className="w-full bg-gray-800/60 border border-white/10 rounded-lg pl-8 pr-8 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                        />
                        {searchQuery && (
                            <button onClick={() => setSearchQuery('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white">
                                <X size={12} />
                            </button>
                        )}
                    </div>
                    <button
                        onClick={handleSearch}
                        disabled={!isSearching || searchMutation.isPending}
                        className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-xs rounded-lg transition-colors shrink-0"
                    >
                        Search
                    </button>
                    <button
                        onClick={() => { resetEntryForm(); setShowAdd(true); }}
                        className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded-lg flex items-center gap-1 transition-colors shrink-0"
                    >
                        <Plus size={12} /> Add
                    </button>
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept=".json"
                        className="hidden"
                        onChange={handleImportFile}
                    />
                    <button
                        onClick={() => fileInputRef.current?.click()}
                        disabled={importEntries.isPending}
                        className="p-1.5 text-gray-400 hover:text-white border border-white/10 rounded-lg transition-colors shrink-0 disabled:opacity-50"
                        title="Import SillyTavern world-book JSON into this book"
                    >
                        <Upload size={14} />
                    </button>
                    {selectedIds.size > 0 && (
                        <button
                            onClick={handleBulkDelete}
                            disabled={bulkDeleteEntries.isPending}
                            className="px-3 py-1.5 bg-red-600/80 hover:bg-red-600 text-white text-xs rounded-lg flex items-center gap-1 transition-colors shrink-0 disabled:opacity-50"
                        >
                            <Trash2 size={12} /> Delete ({selectedIds.size})
                        </button>
                    )}
                    <button
                        onClick={handleReindex}
                        disabled={reindexMutation.isPending}
                        className="p-1.5 text-gray-400 hover:text-white border border-white/10 rounded-lg transition-colors shrink-0"
                        title="Reindex embeddings"
                    >
                        <RefreshCw size={14} className={reindexMutation.isPending ? 'animate-spin' : ''} />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-4 space-y-2">
                    {showAdd && (
                        <div className="bg-gray-800/60 border border-blue-500/20 rounded-xl p-3 space-y-2">
                            <input
                                type="text"
                                value={entryForm.keys}
                                onChange={(e) => setEntryForm(f => ({ ...f, keys: e.target.value }))}
                                placeholder="Trigger keys (comma-separated, e.g. dragon, wyrm)"
                                className="w-full bg-gray-900/60 border border-white/10 text-xs rounded-lg px-3 py-1.5 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/40"
                            />
                            <textarea
                                value={entryForm.content}
                                onChange={(e) => setEntryForm(f => ({ ...f, content: e.target.value }))}
                                placeholder="Entry content..."
                                rows={3}
                                className="w-full bg-gray-900/60 border border-white/10 text-xs rounded-lg px-3 py-1.5 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/40 resize-none"
                            />
                            <div className="flex justify-end gap-2">
                                <button onClick={resetEntryForm} className="px-3 py-1 text-xs text-gray-400 hover:text-white">Cancel</button>
                                <button
                                    onClick={handleSaveEntry}
                                    disabled={createEntry.isPending || updateEntry.isPending}
                                    className="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded-lg flex items-center gap-1"
                                >
                                    <Save size={12} /> {editingEntry ? 'Update' : 'Add'}
                                </button>
                            </div>
                        </div>
                    )}

                    {isLoading ? (
                        <div className="space-y-2">
                            {[1, 2, 3].map(i => (
                                <div key={i} className="bg-gray-800/40 rounded-lg p-3 animate-pulse">
                                    <div className="h-3 bg-gray-700 rounded w-1/3 mb-2" />
                                    <div className="h-3 bg-gray-700 rounded w-2/3" />
                                </div>
                            ))}
                        </div>
                    ) : displayed.length === 0 ? (
                        <p className="text-xs text-gray-500 text-center py-8">
                            {isSearching ? 'No matching entries' : 'No entries yet. Add the first one.'}
                        </p>
                    ) : (
                        displayed.map((entry) => (
                            <div key={entry.id} className="bg-gray-800/40 hover:bg-gray-800/60 rounded-lg p-3 border border-white/5 group">
                                <div className="flex items-start justify-between gap-2">
                                    <input
                                        type="checkbox"
                                        checked={selectedIds.has(entry.id)}
                                        onChange={() => toggleSelected(entry.id)}
                                        className="mt-0.5 shrink-0 accent-blue-500"
                                        aria-label={`Select entry ${entry.keys?.join(', ') || 'without keys'}`}
                                    />
                                    <div className="flex-1 min-w-0">
                                        {entry.keys?.length > 0 && (
                                            <div className="flex flex-wrap gap-1 mb-1.5">
                                                {entry.keys.map((k) => (
                                                    <span key={k} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-xs bg-indigo-500/15 text-indigo-300 rounded border border-indigo-500/25">
                                                        <Key size={9} /> {k}
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                        <p className="text-xs text-gray-200 whitespace-pre-wrap break-words">{entry.content}</p>
                                    </div>
                                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 shrink-0">
                                        <button onClick={() => openEdit(entry)} className="p-1 text-gray-400 hover:text-blue-400 rounded" title="Edit">
                                            <Edit3 size={12} />
                                        </button>
                                        <button onClick={() => handleDeleteEntry(entry)} className="p-1 text-red-500/70 hover:text-red-400 rounded" title="Delete">
                                            <Trash2 size={12} />
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </motion.div>
        </motion.div>
    );
}
