import React, { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Edit3, Trash2, Search, Swords, X, MessageSquare, BookOpen, MapPin, Users, ChevronRight, Check } from 'lucide-react';
import toast from 'react-hot-toast';
import { useNavigate } from 'react-router-dom';
import {
    useCampaigns,
    useCreateCampaign,
    useUpdateCampaign,
    useDeleteCampaign,
    useCampaignDashboard,
} from '../hooks/useCampaigns';
import { useCharacters } from '../hooks/useCharacters';
import { useStories } from '../hooks/useStories';
import { useChats } from '../hooks/useChats';
import { useLocations } from '../hooks/useLocations';
import EmptyState from '../components/EmptyState';
import { useConfirmation } from '../store/confirmationStore';

const FORM_FIELDS = [
    { key: 'name', label: 'Name', type: 'text', required: true, placeholder: 'Campaign name' },
    { key: 'description', label: 'Description', type: 'textarea', placeholder: 'Overview of this campaign...' },
];

const DEFAULT_FORM = {
    name: '',
    description: '',
    character_ids: [],
    story_ids: [],
    chat_ids: [],
    location_ids: [],
};

export default function Campaigns() {
    const [searchQuery, setSearchQuery] = useState('');
    const [showForm, setShowForm] = useState(false);
    const [editingCampaign, setEditingCampaign] = useState(null);
    const [form, setForm] = useState(DEFAULT_FORM);
    const [selectedCampaign, setSelectedCampaign] = useState(null);

    const { data: campaigns = [], isLoading } = useCampaigns();
    const createMutation = useCreateCampaign();
    const updateMutation = useUpdateCampaign();
    const deleteMutation = useDeleteCampaign();
    const { confirm } = useConfirmation();
    const navigate = useNavigate();

    const filteredCampaigns = useMemo(() => {
        if (!searchQuery.trim()) return campaigns;
        const q = searchQuery.toLowerCase();
        return campaigns.filter(c =>
            c.name?.toLowerCase().includes(q) ||
            (c.description && c.description.toLowerCase().includes(q))
        );
    }, [campaigns, searchQuery]);

    const resetForm = () => {
        setForm(DEFAULT_FORM);
        setEditingCampaign(null);
        setShowForm(false);
    };

    const handleSave = async () => {
        if (!form.name.trim()) {
            toast.error('Name is required');
            return;
        }
        try {
            const payload = { ...form, name: form.name.trim() };
            if (editingCampaign) {
                await updateMutation.mutateAsync({ id: editingCampaign.id, ...payload });
                toast.success('Campaign updated');
            } else {
                await createMutation.mutateAsync(payload);
                toast.success('Campaign created');
            }
            resetForm();
        } catch {
            toast.error('Failed to save campaign');
        }
    };

    const handleEdit = (campaign) => {
        setEditingCampaign(campaign);
        setForm({
            name: campaign.name || '',
            description: campaign.description || '',
            character_ids: campaign.character_ids || [],
            story_ids: campaign.story_ids || [],
            chat_ids: campaign.chat_ids || [],
            location_ids: campaign.location_ids || [],
        });
        setShowForm(true);
    };

    const handleDelete = async (campaign) => {
        const ok = await confirm({
            title: 'Delete Campaign',
            message: `Are you sure you want to delete "${campaign.name}"?`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            await deleteMutation.mutateAsync(campaign.id);
            toast.success('Campaign deleted');
        } catch {
            toast.error('Failed to delete campaign');
        }
    };

    return (
        <div className="p-6 max-w-5xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold text-white mb-1">Campaigns</h1>
                    <p className="text-gray-400 text-sm">Organize your stories, characters, and locations into chronicles</p>
                </div>
                <button
                    onClick={() => { resetForm(); setShowForm(true); }}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors"
                >
                    <Plus size={16} /> New Campaign
                </button>
            </div>

            <div className="mb-6">
                <div className="relative max-w-md">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search campaigns..."
                        className="w-full pl-10 pr-4 py-2.5 bg-gray-800/60 border border-white/10 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                    />
                </div>
            </div>

            {isLoading ? (
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
            ) : filteredCampaigns.length === 0 ? (
                <EmptyState
                    icon={Swords}
                    title="No campaigns yet"
                    description="Create your first campaign to start organizing your world."
                />
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {filteredCampaigns.map((campaign) => (
                        <CampaignCard
                            key={campaign.id}
                            campaign={campaign}
                            onEdit={handleEdit}
                            onDelete={handleDelete}
                            onOpen={setSelectedCampaign}
                        />
                    ))}
                </div>
            )}

            <AnimatePresence>
                {showForm && (
                    <CampaignFormModal
                        campaign={editingCampaign}
                        form={form}
                        setForm={setForm}
                        onSave={handleSave}
                        onClose={resetForm}
                        isSubmitting={createMutation.isPending || updateMutation.isPending}
                    />
                )}
            </AnimatePresence>

            <AnimatePresence>
                {selectedCampaign && (
                    <CampaignDashboardModal
                        campaignId={selectedCampaign.id}
                        onClose={() => setSelectedCampaign(null)}
                        onNavigate={(path) => { setSelectedCampaign(null); navigate(path); }}
                    />
                )}
            </AnimatePresence>
        </div>
    );
}

function CampaignCard({ campaign, onEdit, onDelete, onOpen }) {
    return (
        <motion.div
            layout
            className="p-5 rounded-xl border border-white/10 bg-gray-800/40 hover:bg-gray-800/60 hover:border-white/20 transition-all group"
        >
            <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3 min-w-0">
                    <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-red-500/20 to-orange-500/20 border border-white/10 flex items-center justify-center shrink-0">
                        <Swords size={20} className="text-orange-400" />
                    </div>
                    <div className="min-w-0">
                        <h3 className="font-semibold text-white truncate">{campaign.name}</h3>
                        {campaign.description && (
                            <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">{campaign.description}</p>
                        )}
                    </div>
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    <button onClick={() => onOpen(campaign)} className="p-1 text-gray-400 hover:text-blue-400 rounded" title="Open">
                        <ChevronRight size={12} />
                    </button>
                    <button onClick={() => onEdit(campaign)} className="p-1 text-gray-400 hover:text-white rounded" title="Edit">
                        <Edit3 size={12} />
                    </button>
                    <button onClick={() => onDelete(campaign)} className="p-1 text-gray-400 hover:text-red-400 rounded" title="Delete">
                        <Trash2 size={12} />
                    </button>
                </div>
            </div>
            <div className="flex items-center gap-4 text-xs text-gray-500">
                {(campaign.character_ids?.length || 0) > 0 && (
                    <span className="flex items-center gap-1"><Users size={12} /> {campaign.character_ids.length}</span>
                )}
                {(campaign.story_ids?.length || 0) > 0 && (
                    <span className="flex items-center gap-1"><BookOpen size={12} /> {campaign.story_ids.length}</span>
                )}
                {(campaign.chat_ids?.length || 0) > 0 && (
                    <span className="flex items-center gap-1"><MessageSquare size={12} /> {campaign.chat_ids.length}</span>
                )}
                {(campaign.location_ids?.length || 0) > 0 && (
                    <span className="flex items-center gap-1"><MapPin size={12} /> {campaign.location_ids.length}</span>
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

function CampaignFormModal({ campaign, form, setForm, onSave, onClose, isSubmitting }) {
    const { data: characters = [] } = useCharacters();
    const { data: stories = [] } = useStories();
    const { data: chats = [] } = useChats();
    const { data: locations = [] } = useLocations();

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
                initial={{ opacity: 0, scale: 0.95, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 10 }}
                className="bg-gray-900 border border-white/10 rounded-2xl p-6 w-full max-w-lg shadow-2xl"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">
                        {campaign ? 'Edit Campaign' : 'New Campaign'}
                    </h2>
                    <button onClick={onClose} className="text-gray-400 hover:text-white">
                        <X size={20} />
                    </button>
                </div>
                {FORM_FIELDS.map(field => (
                    <div key={field.key}>
                        <label className="block text-sm font-medium text-gray-300 mb-1">{field.label}{field.required && '*'}</label>
                        {field.type === 'textarea' ? (
                            <textarea
                                className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                                value={form[field.key] || ''}
                                onChange={(e) => setForm(f => ({ ...f, [field.key]: e.target.value }))}
                                placeholder={field.placeholder}
                                rows={3}
                            />
                        ) : (
                            <input
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
                        {campaign ? 'Update' : 'Create'}
                    </button>
                </div>
            </motion.div>
        </motion.div>
    );
}

function CampaignDashboardModal({ campaignId, onClose, onNavigate }) {
    const { data, isLoading } = useCampaignDashboard(campaignId);

    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
            onClick={onClose}
        >
            <motion.div
                initial={{ opacity: 0, scale: 0.95, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 10 }}
                className="bg-gray-900 border border-white/10 rounded-2xl p-6 w-full max-w-2xl shadow-2xl max-h-[80vh] overflow-y-auto"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">{data?.campaign?.name || 'Campaign Dashboard'}</h2>
                    <button onClick={onClose} className="text-gray-400 hover:text-white">
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
                ) : (
                    <div className="space-y-6">
                        {data?.description && (
                            <p className="text-sm text-gray-400">{data.description}</p>
                        )}
                        <div className="grid grid-cols-2 gap-4">
                            <DashboardSection title="Characters" items={data?.characters || []} onNavigate={() => onNavigate(`/characters`)} icon={Users} />
                            <DashboardSection title="Stories" items={data?.stories || []} onNavigate={() => onNavigate(`/story`)} icon={BookOpen} />
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
