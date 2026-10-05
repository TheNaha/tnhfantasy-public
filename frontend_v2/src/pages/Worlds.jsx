import React, { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Edit3, Trash2, Search, Globe2, X, MessageSquare, BookOpen, MapPin, Users, ChevronRight, Check, AlertTriangle } from 'lucide-react';
import toast from 'react-hot-toast';
import { useNavigate } from 'react-router-dom';
import {
    useWorlds,
    useCreateWorld,
    useUpdateWorld,
    useDeleteWorld,
    useWorldDashboard,
} from '../hooks/useWorlds';
import { useCharacters } from '../hooks/useCharacters';
import { useStories } from '../hooks/useStories';
import { useChats } from '../hooks/useChats';
import { useLocations } from '../hooks/useLocations';
import { useEscapeKey } from '../hooks/useEscapeKey';
import EmptyState from '../components/EmptyState';
import { useConfirmation } from '../store/confirmationStore';
import RoleplayPageShell from '../components/RoleplayPageShell';

const FORM_FIELDS = [
    { key: 'name', label: 'Name', type: 'text', required: true, placeholder: 'World name' },
    { key: 'description', label: 'Description', type: 'textarea', placeholder: 'Overview of this world...' },
];

const DEFAULT_FORM = {
    name: '',
    description: '',
    character_ids: [],
    story_ids: [],
    chat_ids: [],
    location_ids: [],
};

export default function Worlds() {
    const [searchQuery, setSearchQuery] = useState('');
    const [showForm, setShowForm] = useState(false);
    const [editingWorld, setEditingWorld] = useState(null);
    const [form, setForm] = useState(DEFAULT_FORM);
    const [selectedWorld, setSelectedWorld] = useState(null);

    // `isError` is load-bearing, not decoration. The `/api/v2/campaigns` 404 that
    // this page replaces had no error branch at all, so a failed fetch rendered
    // "No campaigns yet" with a working "New Campaign" button — indistinguishable
    // from a genuinely empty vault, and the reason the dead route survived three
    // audits behind a green suite.
    const { data: worlds = [], isLoading, isError, error, refetch } = useWorlds();
    const createMutation = useCreateWorld();
    const updateMutation = useUpdateWorld();
    const deleteMutation = useDeleteWorld();
    const { confirm } = useConfirmation();
    const navigate = useNavigate();

    const filteredWorlds = useMemo(() => {
        if (!searchQuery.trim()) return worlds;
        const q = searchQuery.toLowerCase();
        return worlds.filter(w =>
            w.name?.toLowerCase().includes(q) ||
            (w.description && w.description.toLowerCase().includes(q))
        );
    }, [worlds, searchQuery]);

    const resetForm = () => {
        setForm(DEFAULT_FORM);
        setEditingWorld(null);
        setShowForm(false);
    };

    const handleSave = async () => {
        if (!form.name.trim()) {
            toast.error('Name is required');
            return;
        }
        try {
            const payload = { ...form, name: form.name.trim() };
            if (editingWorld) {
                await updateMutation.mutateAsync({ id: editingWorld.id, ...payload });
                toast.success('World updated');
            } else {
                await createMutation.mutateAsync(payload);
                toast.success('World created');
            }
            resetForm();
        } catch {
            toast.error('Failed to save world');
        }
    };

    const handleEdit = (world) => {
        setEditingWorld(world);
        setForm({
            name: world.name || '',
            description: world.description || '',
            character_ids: world.character_ids || [],
            story_ids: world.story_ids || [],
            chat_ids: world.chat_ids || [],
            location_ids: world.location_ids || [],
        });
        setShowForm(true);
    };

    const handleDelete = async (world) => {
        const ok = await confirm({
            title: 'Delete World',
            message: `Are you sure you want to delete "${world.name}"?`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            await deleteMutation.mutateAsync(world.id);
            toast.success('World deleted');
        } catch {
            toast.error('Failed to delete world');
        }
    };

    return (
        <RoleplayPageShell
            title="Worlds"
            description="Organize your characters, chats, stories, and locations into worlds."
            icon={Globe2}
            actions={
                <button
                    onClick={() => { resetForm(); setShowForm(true); }}
                    className="flex items-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 font-medium text-slate-950 transition hover:bg-cyan-400"
                >
                    <Plus size={16} /> New World
                </button>
            }
        >

            <div className="mb-6">
                <div className="relative max-w-md">
                    <Search className="absolute left-3 top-1/2 -translate-y-2xl -translate-y-1/2 text-gray-400" size={18} />
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        aria-label="Search worlds" placeholder="Search worlds..."
                        className="w-full pl-10 pr-4 py-2.5 bg-gray-800/60 border border-white/10 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                    />
                </div>
            </div>

            {isError ? (
                <div role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-6 flex items-start gap-3">
                    <AlertTriangle className="text-red-400 shrink-0 mt-0.5" size={20} />
                    <div className="flex-1">
                        <h3 className="font-semibold text-red-300">Could not load your worlds</h3>
                        <p className="text-sm text-red-200/70 mt-1 break-words">
                            {error?.message || 'The request failed.'} This is not the same as having no worlds —
                            nothing below is a real list until this succeeds.
                        </p>
                        <button
                            onClick={() => refetch()}
                            className="mt-3 px-4 py-2 rounded-lg bg-red-500/20 border border-red-500/40 text-red-200 text-sm font-medium hover:bg-red-500/30 transition-colors"
                        >
                            Try again
                        </button>
                    </div>
                </div>
            ) : isLoading ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {[1, 2, 3, 4].map(i => (
                        <div key={i} className="p-4 rounded-xl border border-white/10 bg-gray-800/40 animate-pulse">
                            <div className="flex justify-between items-start mb-3">
                                <div className="flex items-center gap-3">
                                    <div className="w-10 h-10 rounded-lg bg-gray-700" />
                                    <div>
                                        <div className="h-5 bg-gray-700 rounded w-32 mb-1" />
                                        <div className="h-4 bg-gray-700 rounded w-20" />
                                    </div>
                                </div>
                            </div>
                            <div className="h-4 bg-gray-700 rounded w-full mb-2" />
                            <div className="h-4 bg-gray-700 rounded w-5/6" />
                        </div>
                    ))}
                </div>
            ) : filteredWorlds.length === 0 ? (
                <EmptyState
                    type="roleplay"
                    icon={Globe2}
                    title="No worlds yet"
                    description="Create your first world to start organizing your vault."
                    primaryLabel="New World"
                    onAction={() => { resetForm(); setShowForm(true); }}
                />
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {filteredWorlds.map((world) => (
                        <WorldCard
                            key={world.id}
                            world={world}
                            onEdit={handleEdit}
                            onDelete={handleDelete}
                            onOpen={setSelectedWorld}
                        />
                    ))}
                </div>
            )}

            <AnimatePresence>
                {showForm && (
                    <WorldFormModal
                        world={editingWorld}
                        form={form}
                        setForm={setForm}
                        onSave={handleSave}
                        onClose={resetForm}
                        isSubmitting={createMutation.isPending || updateMutation.isPending}
                    />
                )}
            </AnimatePresence>

            <AnimatePresence>
                {selectedWorld && (
                    <WorldDashboardModal
                        worldId={selectedWorld.id}
                        onClose={() => setSelectedWorld(null)}
                        onNavigate={(path) => { setSelectedWorld(null); navigate(path); }}
                    />
                )}
            </AnimatePresence>
        </RoleplayPageShell>
    );
}

function WorldCard({ world, onEdit, onDelete, onOpen }) {
    return (
        <motion.div
            layout
            className="p-5 rounded-xl border border-white/10 bg-gray-800/40 hover:bg-gray-800/60 hover:border-white/20 transition-all group"
        >
            <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3 min-w-0">
                    <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-500/20 to-blue-500/20 border border-white/10 flex items-center justify-center shrink-0">
                        <Globe2 size={20} className="text-cyan-400" />
                    </div>
                    <div className="min-w-0 flex-1">
                        {/* `line-clamp-2 sm:truncate`, not `truncate`: a world's
                            name is how you tell two worlds apart, and `truncate`
                            gave it 78px of a 312px card on a phone — "Coherence
                            smoke" lost 44% of itself. Truncation is only
                            acceptable from `sm:` up, where the card is wide
                            enough to show the name in full. */}
                        <h3 className="font-semibold text-white line-clamp-2 sm:truncate">{world.name}</h3>
                        {world.description && (
                            <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">{world.description}</p>
                        )}
                    </div>
                </div>
                {/* `opacity-100 sm:opacity-0 sm:group-hover:opacity-100`: a
                    hover-revealed control is unreachable on touch — there is no
                    hover, so the row was permanently invisible while still
                    occupying ~80px of the title's row. The card itself is not
                    clickable (`onOpen` is only on the first button here), so
                    hiding it on mobile would remove the only way into the world
                    rather than tidy the layout. Visible on phones, hover-revealed
                    on desktop. */}
                <div className="flex items-center gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity shrink-0">
                    <button onClick={() => onOpen(world)} className="p-1 text-gray-400 hover:text-blue-400 rounded" title="Open">
                        <ChevronRight size={12} />
                    </button>
                    <button onClick={() => onEdit(world)} className="p-1 text-gray-400 hover:text-white rounded" title="Edit">
                        <Edit3 size={12} />
                    </button>
                    <button onClick={() => onDelete(world)} className="p-1 text-gray-400 hover:text-red-400 rounded" title="Delete">
                        <Trash2 size={12} />
                    </button>
                </div>
            </div>
            <div className="flex items-center gap-4 text-xs text-gray-500">
                {(world.character_ids?.length || 0) > 0 && (
                    <span className="flex items-center gap-1"><Users size={12} /> {world.character_ids.length}</span>
                )}
                {(world.story_ids?.length || 0) > 0 && (
                    <span className="flex items-center gap-1"><BookOpen size={12} /> {world.story_ids.length}</span>
                )}
                {(world.chat_ids?.length || 0) > 0 && (
                    <span className="flex items-center gap-1"><MessageSquare size={12} /> {world.chat_ids.length}</span>
                )}
                {(world.location_ids?.length || 0) > 0 && (
                    <span className="flex items-center gap-1"><MapPin size={12} /> {world.location_ids.length}</span>
                )}
            </div>
        </motion.div>
    );
}

function EntityPicker({ title, icon: Icon, items, selected, onChange, getLabel }) {
    return (
        <div>
            <label className="block text-sm font-medium text-gray-300 mb-1 flex items-center gap-1.5">
                <Icon size={13} /> {title}
            </label>
            {items.length === 0 ? (
                <p className="text-xs text-gray-600 border border-gray-700/50 rounded-lg px-3 py-2">
                    None available — create {title.toLowerCase()} first
                </p>
            ) : (
                <div className="max-h-40 overflow-y-auto border border-gray-600 rounded-lg bg-gray-800/60 divide-y divide-white/5">
                    {items.map(item => {
                        const active = selected.includes(item.id);
                        return (
                            <button
                                key={item.id}
                                type="button"
                                onClick={() => onChange(item.id)}
                                className={
                                    'w-full flex items-center gap-2 px-3 py-2 text-left text-xs transition-colors ' +
                                    (active ? 'bg-indigo-500/20 text-indigo-300' : 'text-gray-400 hover:bg-white/5')
                                }
                            >
                                {active ? (
                                    <Check size={12} className="text-indigo-400 shrink-0" />
                                ) : (
                                    <div className="w-3 h-3 rounded border border-gray-600 shrink-0" />
                                )}
                                <span className="truncate">{getLabel(item)}</span>
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

function WorldFormModal({ world, form, setForm, onSave, onClose, isSubmitting }) {
    const { data: characters = [] } = useCharacters();
    const { data: stories = [] } = useStories();
    const { data: chats = [] } = useChats();
    const { data: locations = [] } = useLocations();

    useEscapeKey(onClose, true);

    const toggle = (field, id) => {
        setForm(f => ({
            ...f,
            [field]: f[field].includes(id) ? f[field].filter(x => x !== id) : [...f[field], id],
        }));
    };

    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
            onClick={(e) => e.target === e.currentTarget && onClose()}
        >
            <motion.div
                role="dialog"
                aria-modal="true"
                aria-label={world ? 'Edit World' : 'New World'}
                initial={{ opacity: 0, scale: 0.95, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 10 }}
                className="bg-gray-900 border border-white/10 rounded-2xl p-6 w-full max-w-lg shadow-2xl max-h-[80vh] overflow-y-auto"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">
                        {world ? 'Edit World' : 'New World'}
                    </h2>
                    <button onClick={onClose} aria-label={world ? 'Cancel editing world' : 'Close world form'} className="text-gray-400 hover:text-white">
                        <X size={20} />
                    </button>
                </div>
                {FORM_FIELDS.map(field => (
                    <div key={field.key}>
                        <label htmlFor={`world-field-${field.key}`} className="block text-sm font-medium text-gray-300 mb-1">{field.label}{field.required && '*'}</label>
                        {field.type === 'textarea' ? (
                            <textarea
                                id={`world-field-${field.key}`}
                                className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                                value={form[field.key] || ''}
                                onChange={(e) => setForm(f => ({ ...f, [field.key]: e.target.value }))}
                                placeholder={field.placeholder}
                                rows={3}
                            />
                        ) : (
                            <input
                                id={`world-field-${field.key}`}
                                type={field.type}
                                className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                                value={form[field.key] || ''}
                                onChange={(e) => setForm(f => ({ ...f, [field.key]: e.target.value }))}
                                placeholder={field.placeholder}
                            />
                        )}
                    </div>
                ))}
                <div className="space-y-3 mt-4">
                    <EntityPicker
                        title="Characters"
                        icon={Users}
                        items={characters}
                        selected={form.character_ids}
                        onChange={(id) => toggle('character_ids', id)}
                        getLabel={(c) => c.name}
                    />
                    <EntityPicker
                        title="Stories"
                        icon={BookOpen}
                        items={stories}
                        selected={form.story_ids}
                        onChange={(id) => toggle('story_ids', id)}
                        getLabel={(s) => s.title}
                    />
                    <EntityPicker
                        title="Chats"
                        icon={MessageSquare}
                        items={chats}
                        selected={form.chat_ids}
                        onChange={(id) => toggle('chat_ids', id)}
                        getLabel={(c) => c.name}
                    />
                    <EntityPicker
                        title="Locations"
                        icon={MapPin}
                        items={locations}
                        selected={form.location_ids}
                        onChange={(id) => toggle('location_ids', id)}
                        getLabel={(l) => l.name}
                    />
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
                        {world ? 'Update' : 'Create'}
                    </button>
                </div>
            </motion.div>
        </motion.div>
    );
}

function WorldDashboardModal({ worldId, onClose, onNavigate }) {
    const { data, isLoading, isError } = useWorldDashboard(worldId);

    useEscapeKey(onClose, true);

    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
            onClick={onClose}
        >
            <motion.div
                role="dialog"
                aria-modal="true"
                aria-label="World dashboard"
                initial={{ opacity: 0, scale: 0.95, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 10 }}
                className="bg-gray-900 border border-white/10 rounded-2xl p-6 w-full max-w-2xl shadow-2xl max-h-[80vh] overflow-y-auto"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">{data?.world?.name || 'World Dashboard'}</h2>
                    <button onClick={onClose} aria-label="Close world dashboard" className="text-gray-400 hover:text-white">
                        <X size={20} />
                    </button>
                </div>

                {isLoading ? (
                    <div className="space-y-6">
                        <div className="grid grid-cols-2 gap-4">
                            {[1, 2, 3, 4].map(i => (
                                <div key={i} className="bg-gray-800/40 rounded-xl p-4 border border-white/5 animate-pulse">
                                    <div className="h-5 bg-gray-700 rounded w-1/3 mb-4" />
                                    <div className="space-y-2">
                                        <div className="h-8 bg-gray-700 rounded w-full" />
                                        <div className="h-8 bg-gray-700 rounded w-full" />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                ) : isError ? (
                    <p role="alert" className="text-sm text-red-300">
                        Could not load this world's contents. The counts below would be a guess, so they are not shown.
                    </p>
                ) : (
                    <div className="space-y-6">
                        {data?.world?.description && (
                            <p className="text-sm text-gray-400">{data.world.description}</p>
                        )}
                        <div className="grid grid-cols-2 gap-4">
                            <DashboardSection title="Characters" items={data?.characters || []} onNavigate={(cid) => onNavigate(`/characters#char-${cid}`)} icon={Users} />
                            <DashboardSection title="Stories" items={data?.stories || []} onNavigate={(sid) => onNavigate(`/story/${sid}`)} icon={BookOpen} />
                            <DashboardSection title="Chats" items={data?.chats || []} onNavigate={(cid) => onNavigate(`/chat/${cid}`)} icon={MessageSquare} />
                            <DashboardSection title="Locations" items={data?.locations || []} onNavigate={() => onNavigate(`/locations`)} icon={MapPin} />
                        </div>
                    </div>
                )}
            </motion.div>
        </motion.div>
    );
}

function DashboardSection({ title, items, onNavigate, icon: Icon }) {
    return (
        <div className="p-4 bg-gray-800/40 border border-white/10 rounded-xl">
            <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
                <Icon size={14} /> {title} ({items.length})
            </h3>
            {items.length === 0 ? (
                <p className="text-xs text-gray-500">None yet</p>
            ) : (
                <div className="space-y-2">
                    {items.slice(0, 5).map((item, idx) => (
                        <button
                            key={idx}
                            onClick={() => onNavigate(item.id)}
                            className="w-full text-left text-xs text-gray-400 hover:text-white truncate p-1.5 rounded hover:bg-white/5 transition-colors"
                        >
                            {item.name || item.title || item.id.slice(0, 8)}
                        </button>
                    ))}
                    {items.length > 5 && (
                        <p className="text-xs text-gray-500">+{items.length - 5} more</p>
                    )}
                </div>
            )}
        </div>
    );
}
