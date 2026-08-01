import React, { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Users, Plus, Upload, Search, Edit3, Trash2, MessageSquare, X, Loader2, User } from 'lucide-react';
import toast from 'react-hot-toast';
import { useNavigate } from 'react-router-dom';
import { useCharacters, useCreateCharacter, useUpdateCharacter, useDeleteCharacter } from '../hooks/useWorldVault';
import { useWorldVaultStore } from '../store/worldVaultStore';
import EmptyState from '../components/EmptyState';
import ConfirmationModal from '../components/ConfirmationModal';

const CHARACTER_FIELDS = [
    { key: 'name', label: 'Name', type: 'text', required: true, placeholder: 'Character name' },
    { key: 'description', label: 'Description', type: 'textarea', placeholder: 'A brief description of the character...' },
    { key: 'personality', label: 'Personality', type: 'textarea', placeholder: 'How does this character behave? Traits, quirks, mannerisms...' },
    { key: 'scenario', label: 'Scenario', type: 'textarea', placeholder: 'The situation or setting for this character...' },
    { key: 'first_mes', label: 'First Message', type: 'textarea', placeholder: 'The character\'s opening message (greeting)...' },
    { key: 'mes_example', label: 'Message Examples', type: 'textarea', placeholder: 'Example messages showing how the character speaks...' },
    { key: 'system_prompt', label: 'System Prompt', type: 'textarea', placeholder: 'Custom system prompt (leave empty to auto-generate from fields above)...' },
    { key: 'creator_notes', label: 'Creator Notes', type: 'textarea', placeholder: 'Notes about this character...' },
];

const DEFAULT_FORM = {
    name: '', description: '', personality: '', scenario: '',
    first_mes: '', mes_example: '', system_prompt: '', creator_notes: '',
    visual_tags: [], lora_triggers: [], voice_profile: '',
};

function CharacterModal({ isOpen, onClose, character, onSave }) {
    const [form, setForm] = useState(() => {
        if (character) {
            return {
                name: character.name || '',
                description: character.description || '',
                personality: character.personality || '',
                scenario: character.scenario || '',
                first_mes: character.first_mes || '',
                mes_example: character.mes_example || '',
                system_prompt: character.system_prompt || '',
                creator_notes: character.creator_notes || '',
                visual_tags: character.visual_tags || [],
                lora_triggers: character.lora_triggers || [],
                voice_profile: character.voice_profile || '',
            };
        }
        return { ...DEFAULT_FORM };
    });
    const [visualTagInput, setVisualTagInput] = useState('');
    const [loraTagInput, setLoraTagInput] = useState('');
    const [saving, setSaving] = useState(false);

    const isEditing = !!character;

    const handleSave = async () => {
        if (!form.name.trim()) {
            toast.error('Character name is required');
            return;
        }
        setSaving(true);
        try {
            await onSave(form);
            toast.success(isEditing ? 'Character updated' : 'Character created');
            onClose();
        } catch (err) {
            toast.error(err?.message || 'Failed to save character');
        } finally {
            setSaving(false);
        }
    };

    const addTag = (field, value, setValue) => {
        const val = value.trim();
        if (val && !form[field].includes(val)) {
            setForm(f => ({ ...f, [field]: [...f[field], val] }));
            setValue('');
        }
    };

    const removeTag = (field, idx) => {
        setForm(f => ({ ...f, [field]: f[field].filter((_, i) => i !== idx) }));
    };

    if (!isOpen) return null;

    return (
        <AnimatePresence>
            <div className="fixed inset-0 z-[90] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm" onClick={onClose}>
                <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    className="bg-gray-900 rounded-xl border border-gray-700 w-full max-w-2xl max-h-[85vh] shadow-2xl flex flex-col"
                    onClick={e => e.stopPropagation()}
                >
                    <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700/50 shrink-0">
                        <h2 className="text-lg font-bold text-gray-100">{isEditing ? 'Edit Character' : 'Create Character'}</h2>
                        <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors"><X size={20} /></button>
                    </div>

                    <div className="flex-1 overflow-y-auto p-6 space-y-5 custom-scrollbar">
                        <div className="flex items-center gap-4">
                            <div className="w-16 h-16 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0">
                                <User size={28} className="text-gray-500" />
                            </div>
                            <div className="flex-1">
                                <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Name *</label>
                                <input
                                    type="text"
                                    value={form.name}
                                    onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                                    className="mt-1 w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-4 py-2 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 transition-all"
                                    placeholder="Character name"
                                />
                            </div>
                        </div>

                        {CHARACTER_FIELDS.filter(f => f.key !== 'name').map(field => (
                            <div key={field.key}>
                                <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">{field.label}</label>
                                <textarea
                                    value={form[field.key]}
                                    onChange={e => setForm(f => ({ ...f, [field.key]: e.target.value }))}
                                    className="mt-1 w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-4 py-2 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 transition-all resize-none"
                                    rows={field.key === 'system_prompt' ? 3 : 4}
                                    placeholder={field.placeholder}
                                />
                            </div>
                        ))}

                        {/* Visual Tags */}
                        <div>
                            <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Visual Tags</label>
                            <p className="text-[11px] text-gray-500 mb-2">Tags for image generation (e.g., 1girl, blue hair, school uniform)</p>
                            <div className="flex flex-wrap gap-2 mb-2">
                                {form.visual_tags.map((tag, idx) => (
                                    <span key={idx} className="px-2 py-1 text-xs bg-purple-500/20 text-purple-300 rounded-full border border-purple-500/30 flex items-center gap-1">
                                        {tag}
                                        <button onClick={() => removeTag('visual_tags', idx)} className="text-purple-400 hover:text-white ml-1"><X size={12} /></button>
                                    </span>
                                ))}
                            </div>
                            <div className="flex gap-2">
                                <input
                                    type="text"
                                    value={visualTagInput}
                                    onChange={e => setVisualTagInput(e.target.value)}
                                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTag('visual_tags', visualTagInput, setVisualTagInput); } }}
                                    className="flex-1 bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                                    placeholder="Add tag..."
                                />
                                <button onClick={() => addTag('visual_tags', visualTagInput, setVisualTagInput)} className="px-3 py-1.5 text-sm bg-purple-500/20 text-purple-300 rounded-lg hover:bg-purple-500/30 transition-colors">Add</button>
                            </div>
                        </div>

                        {/* LoRA Triggers */}
                        <div>
                            <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">LoRA Triggers</label>
                            <p className="text-[11px] text-gray-500 mb-2">LoRA trigger words for this character</p>
                            <div className="flex flex-wrap gap-2 mb-2">
                                {form.lora_triggers.map((tag, idx) => (
                                    <span key={idx} className="px-2 py-1 text-xs bg-blue-500/20 text-blue-300 rounded-full border border-blue-500/30 flex items-center gap-1">
                                        {tag}
                                        <button onClick={() => removeTag('lora_triggers', idx)} className="text-blue-400 hover:text-white ml-1"><X size={12} /></button>
                                    </span>
                                ))}
                            </div>
                            <div className="flex gap-2">
                                <input
                                    type="text"
                                    value={loraTagInput}
                                    onChange={e => setLoraTagInput(e.target.value)}
                                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTag('lora_triggers', loraTagInput, setLoraTagInput); } }}
                                    className="flex-1 bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                                    placeholder="Add LoRA trigger..."
                                />
                                <button onClick={() => addTag('lora_triggers', loraTagInput, setLoraTagInput)} className="px-3 py-1.5 text-sm bg-blue-500/20 text-blue-300 rounded-lg hover:bg-blue-500/30 transition-colors">Add</button>
                            </div>
                        </div>

                        {/* Voice Profile */}
                        <div>
                            <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Voice Profile</label>
                            <input
                                type="text"
                                value={form.voice_profile}
                                onChange={e => setForm(f => ({ ...f, voice_profile: e.target.value }))}
                                className="mt-1 w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-4 py-2 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 transition-all"
                                placeholder="TTS voice profile name (future)"
                            />
                        </div>
                    </div>

                    <div className="flex gap-3 px-6 py-4 border-t border-gray-700/50 shrink-0">
                        <button onClick={onClose} className="flex-1 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-medium transition-colors">Cancel</button>
                        <button onClick={handleSave} disabled={saving} className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium transition-colors shadow-lg shadow-blue-900/20 flex items-center justify-center gap-2">
                            {saving ? <Loader2 size={16} className="animate-spin" /> : null}
                            {isEditing ? 'Update' : 'Create'}
                        </button>
                    </div>
                </motion.div>
            </div>
        </AnimatePresence>
    );
}

function CharacterCard({ character, onEdit, onDelete, onChat }) {
    return (
        <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass-panel rounded-xl border border-white/5 p-4 hover:border-blue-500/30 transition-all group"
        >
            <div className="flex items-start gap-3">
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0 overflow-hidden">
                    {character.avatar_path ? (
                        <img src={character.avatar_path} alt={character.name} className="w-full h-full object-cover" />
                    ) : (
                        <User size={22} className="text-gray-500" />
                    )}
                </div>
                <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-gray-100 truncate">{character.name}</h3>
                    {character.description && (
                        <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">{character.description}</p>
                    )}
                </div>
            </div>

            {character.personality && (
                <p className="text-xs text-gray-500 mt-3 line-clamp-2 italic">"{character.personality}"</p>
            )}

            {character.visual_tags?.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-3">
                    {character.visual_tags.slice(0, 5).map((tag, idx) => (
                        <span key={idx} className="px-1.5 py-0.5 text-[10px] bg-purple-500/10 text-purple-400 rounded border border-purple-500/20">{tag}</span>
                    ))}
                    {character.visual_tags.length > 5 && (
                        <span className="px-1.5 py-0.5 text-[10px] text-gray-500">+{character.visual_tags.length - 5}</span>
                    )}
                </div>
            )}

            <div className="flex items-center gap-2 mt-4 opacity-0 group-hover:opacity-100 transition-opacity">
                <button onClick={() => onChat(character)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-500/20 text-blue-300 rounded-lg hover:bg-blue-500/30 transition-colors" title="Start chat with this character">
                    <MessageSquare size={14} /> Chat
                </button>
                <button onClick={() => onEdit(character)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white/5 text-gray-400 rounded-lg hover:bg-white/10 hover:text-white transition-colors" title="Edit character">
                    <Edit3 size={14} /> Edit
                </button>
                <button onClick={() => onDelete(character)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-red-500/10 text-red-400 rounded-lg hover:bg-red-500/20 transition-colors ml-auto" title="Delete character">
                    <Trash2 size={14} />
                </button>
            </div>
        </motion.div>
    );
}

export default function Characters() {
    const [searchQuery, setSearchQuery] = useState('');
    const [modalOpen, setModalOpen] = useState(false);
    const [editingCharacter, setEditingCharacter] = useState(null);
    const [deleteTarget, setDeleteTarget] = useState(null);

    const navigate = useNavigate();
    const setActiveChat = useWorldVaultStore(state => state.setActiveChat);

    const { data: characters = [], isLoading } = useCharacters();
    const createCharacter = useCreateCharacter();
    const updateCharacter = useUpdateCharacter();
    const deleteCharacter = useDeleteCharacter();

    const filteredCharacters = useMemo(() => {
        if (!searchQuery.trim()) return characters;
        const q = searchQuery.toLowerCase();
        return characters.filter(c =>
            c.name?.toLowerCase().includes(q) ||
            c.description?.toLowerCase().includes(q) ||
            c.personality?.toLowerCase().includes(q) ||
            c.visual_tags?.some(t => t.toLowerCase().includes(q))
        );
    }, [characters, searchQuery]);

    const handleSave = async (form) => {
        const payload = { ...form };
        if (editingCharacter) {
            await updateCharacter.mutateAsync({ id: editingCharacter.id, ...payload });
        } else {
            await createCharacter.mutateAsync(payload);
        }
    };

    const handleDelete = async () => {
        if (!deleteTarget) return;
        try {
            await deleteCharacter.mutateAsync(deleteTarget.id);
            toast.success(`"${deleteTarget.name}" deleted`);
        } catch {
            toast.error('Failed to delete character');
        }
        setDeleteTarget(null);
    };

    const handleStartChat = async (character) => {
        setActiveChat(null);
        navigate('/chat', { state: { characterId: character.id } });
        toast(`Starting chat with ${character.name}...`, { icon: '💬' });
    };

    const openCreate = () => {
        setEditingCharacter(null);
        setModalOpen(true);
    };

    const openEdit = (character) => {
        setEditingCharacter(character);
        setModalOpen(true);
    };

    return (
        <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="flex flex-col h-full"
        >
            {/* Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6 lg:mb-8">
                <div>
                    <h1 className="text-2xl md:text-3xl font-bold text-gray-100 flex items-center gap-3">
                        <Users className="text-blue-500" />
                        Character Vault
                    </h1>
                    <p className="text-gray-400 mt-1 max-w-2xl text-sm">
                        Manage your roleplay characters. Import V2/V3 spec PNG cards or create new ones from scratch.
                    </p>
                </div>
                
                <div className="flex flex-wrap items-center gap-3">
                    <button className="btn-secondary flex items-center gap-2 opacity-50 cursor-not-allowed" disabled title="Coming soon">
                        <Upload size={18} />
                        Import Card
                    </button>
                    <button onClick={openCreate} className="btn-primary flex items-center gap-2">
                        <Plus size={18} />
                        Create Character
                    </button>
                </div>
            </div>

            {/* Search Bar */}
            <div className="glass-panel p-4 mb-6 flex flex-wrap gap-4 items-center">
                <div className="relative flex-1 min-w-[200px]">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
                    <input 
                        type="text" 
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        placeholder="Search characters by name, tags, or description..." 
                        className="w-full bg-gray-900/50 border border-gray-700/50 rounded-lg pl-10 pr-4 py-2 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50 transition-all"
                    />
                </div>
                <div className="text-sm text-gray-500">
                    {filteredCharacters.length} character{filteredCharacters.length !== 1 ? 's' : ''}
                </div>
            </div>

            {/* Character Grid */}
            <div className="flex-1 rounded-xl overflow-hidden">
                {isLoading ? (
                    <div className="flex items-center justify-center p-12">
                        <Loader2 className="animate-spin text-gray-500" size={32} />
                    </div>
                ) : filteredCharacters.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-gray-700/50 flex flex-col items-center justify-center p-8 text-center bg-gray-900/20 h-full min-h-[300px]">
                        <EmptyState
                            type="search"
                            title={searchQuery ? "No Characters Match" : "No Characters Found"}
                            description={searchQuery 
                                ? `No characters match "${searchQuery}". Try a different search.`
                                : "You haven't created any characters yet. Create one to start roleplaying."
                            }
                            primaryLabel={searchQuery ? "Clear Search" : "Create Character"}
                            primaryAction={searchQuery ? () => setSearchQuery('') : openCreate}
                        />
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                        {filteredCharacters.map(character => (
                            <CharacterCard
                                key={character.id}
                                character={character}
                                onEdit={openEdit}
                                onDelete={setDeleteTarget}
                                onChat={handleStartChat}
                            />
                        ))}
                    </div>
                )}
            </div>

            {/* Character Modal */}
            <CharacterModal
                isOpen={modalOpen}
                onClose={() => { setModalOpen(false); setEditingCharacter(null); }}
                character={editingCharacter}
                onSave={handleSave}
            />

            {/* Delete Confirmation */}
            <ConfirmationModal
                isOpen={!!deleteTarget}
                onClose={() => setDeleteTarget(null)}
                onConfirm={handleDelete}
                title="Delete Character"
                message={`Are you sure you want to delete "${deleteTarget?.name}"? This cannot be undone.`}
                confirmText="Delete"
                isDangerous
            />
        </motion.div>
    );
}
