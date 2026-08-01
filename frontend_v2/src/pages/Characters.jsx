import React, { useState, useMemo, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Users, Plus, Upload, Search, Edit3, Trash2, MessageSquare, X, Loader2, User, Images, Sparkles } from 'lucide-react';
import toast from 'react-hot-toast';
import { useNavigate } from 'react-router-dom';
import { useCharacters, useCreateCharacter, useUpdateCharacter, useDeleteCharacter, useUploadAvatar, useCharacterCollection, useImportCharacterCard, getAvatarUrl } from '../hooks/useWorldVault';
import { useWorldVaultStore } from '../store/worldVaultStore';
import useSettingsStore from '../store/settingsStore';
import EmptyState from '../components/EmptyState';
import ConfirmationModal from '../components/ConfirmationModal';
import api from '../api/client';

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
    
    const uploadAvatarMutation = useUploadAvatar();
    const avatarInputRef = React.useRef(null);
    const [previewUrl, setPreviewUrl] = useState(null);

    const handleFileChange = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        
        // Show preview immediately
        const objectUrl = URL.createObjectURL(file);
        setPreviewUrl(objectUrl);

        if (isEditing && character?.id) {
            try {
                await uploadAvatarMutation.mutateAsync({ characterId: character.id, file });
                toast.success('Avatar uploaded successfully');
            } catch {
                toast.error('Failed to upload avatar');
            }
        } else {
            // For new characters, we need to save the file and upload it after creation
            // We'll store it in the form state temporarily
            setForm(f => ({ ...f, _avatarFile: file }));
        }
    };

    const [showGalleryPicker, setShowGalleryPicker] = useState(false);
    const [recentImages, setRecentImages] = useState([]);
    const [loadingGallery, setLoadingGallery] = useState(false);

    const openGalleryPicker = async () => {
        setShowGalleryPicker(true);
        setLoadingGallery(true);
        try {
            const res = await api.get('/api/files?directory=output&limit=12');
            setRecentImages(res.files || []);
        } catch {
            toast.error('Failed to load recent images');
        }
        setLoadingGallery(false);
    };

    const handleSelectGalleryImage = async (img) => {
        try {
            // Fetch metadata to populate fields
            const metaRes = await api.post('/api/files/metadata/batch', { paths: [img.relative_path] });
            const metadata = metaRes.metadata?.[img.relative_path] || {};
            
            if (metadata.prompt) {
                // simple heuristic
                const tags = metadata.prompt.split(',').map(s => s.trim()).filter(Boolean);
                setForm(f => ({
                    ...f,
                    visual_tags: [...new Set([...f.visual_tags, ...tags])]
                }));
                toast.success('Extracted tags from image!');
            }

            // Convert image to file for avatar upload
            const imgRes = await fetch(img.preview);
            const blob = await imgRes.blob();
            const file = new File([blob], img.name, { type: blob.type });
            
            const objectUrl = URL.createObjectURL(file);
            setPreviewUrl(objectUrl);
            
            if (isEditing && character?.id) {
                await uploadAvatarMutation.mutateAsync({ characterId: character.id, file });
                toast.success('Avatar updated from gallery');
            } else {
                setForm(f => ({ ...f, _avatarFile: file }));
            }
        } catch {
            toast.error('Failed to process gallery image');
        }
        setShowGalleryPicker(false);
    };

    const handleSave = async () => {
        if (!form.name.trim()) {
            toast.error('Character name is required');
            return;
        }
        setSaving(true);
        try {
            const result = await onSave(form);
            const savedCharId = isEditing ? character.id : (result?.id || result?.data?.id);
            
            // Upload avatar if a file was selected during creation
            if (!isEditing && form._avatarFile && savedCharId) {
                try {
                    await uploadAvatarMutation.mutateAsync({ characterId: savedCharId, file: form._avatarFile });
                } catch {
                    console.error("Avatar upload failed after creation");
                }
            }
            
            toast.success(isEditing ? 'Character updated' : 'Character created');
            onClose();
            setPreviewUrl(null);
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

    const settings = useSettingsStore(s => s.settings);

    const handleGenerateField = async (fieldKey) => {
        if (!form.name.trim() && !form.description.trim()) {
            toast.error('Provide at least a name or short description first!');
            return;
        }
        
        let sysPrompt = '';
        switch(fieldKey) {
            case 'description': sysPrompt = settings.charGenDescriptionPrompt; break;
            case 'personality': sysPrompt = settings.charGenPersonalityPrompt; break;
            case 'scenario': sysPrompt = settings.charGenScenarioPrompt; break;
            case 'first_mes': sysPrompt = settings.charGenFirstMesPrompt; break;
            case 'mes_example': sysPrompt = settings.charGenMesExamplePrompt; break;
            case 'system_prompt': sysPrompt = settings.charGenSystemPromptPrompt; break;
            case 'visual_tags': sysPrompt = settings.charGenVisualTagsPrompt; break;
            default: return;
        }
        
        let context = `Name: ${form.name}\n`;
        if (form.description && fieldKey !== 'description') context += `Description: ${form.description}\n`;
        if (form.personality && fieldKey !== 'personality') context += `Personality: ${form.personality}\n`;
        if (form.scenario && fieldKey !== 'scenario') context += `Scenario: ${form.scenario}\n`;
        
        toast(`Generating ${fieldKey}...`, { icon: '🤖' });
        try {
            const resJob = await api.post('/api/jobs', {
                task_type: "text",
                workflow: {
                    messages: [
                        { role: "system", content: sysPrompt },
                        { role: "user", content: context }
                    ]
                }
            });
            
            const pollJob = async (jobId) => {
                for (let i = 0; i < 30; i++) {
                    const jobStatus = await api.get(`/api/jobs/${jobId}`);
                    if (jobStatus.status === 'completed' && jobStatus.outputs?.length > 0) {
                        try {
                            const raw = jobStatus.outputs[0].content.trim();
                            if (fieldKey === 'visual_tags') {
                                const tags = raw.split(',').map(s => s.trim()).filter(Boolean);
                                setForm(f => ({ ...f, visual_tags: [...new Set([...f.visual_tags, ...tags])] }));
                            } else {
                                setForm(f => ({ ...f, [fieldKey]: raw }));
                            }
                            toast.success(`Generated field!`);
                        } catch {
                            toast.error('Failed to parse AI output');
                        }
                        return;
                    }
                    if (jobStatus.status === 'failed') break;
                    await new Promise(r => setTimeout(r, 1000));
                }
                toast.error('Generation failed');
            };
            if (resJob.id) {
                pollJob(resJob.id);
            }
        } catch {
            toast.error('Failed to generate profile');
        }
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
                        <div className="flex items-center gap-3">
                            <h2 className="text-lg font-bold text-gray-100">{isEditing ? 'Edit Character' : 'Create Character'}</h2>
                        </div>
                        <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors"><X size={20} /></button>
                    </div>

                    <div className="flex-1 overflow-y-auto p-6 space-y-5 custom-scrollbar">
                        <div className="flex items-center gap-4">
                            <div 
                                className="relative w-20 h-20 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0 cursor-pointer group overflow-hidden"
                                onClick={() => avatarInputRef.current?.click()}
                            >
                                {previewUrl ? (
                                    <img src={previewUrl} alt="Preview" className="w-full h-full object-cover" />
                                ) : (isEditing && character.has_avatar) ? (
                                    <img src={getAvatarUrl(character.id)} alt="Avatar" className="w-full h-full object-cover" />
                                ) : (
                                    <User size={32} className="text-gray-500 group-hover:text-gray-300 transition-colors" />
                                )}
                                <div className="absolute inset-0 bg-black/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                                    <Upload size={20} className="text-white" />
                                </div>
                            </div>
                            <input type="file" ref={avatarInputRef} className="hidden" accept="image/*" onChange={handleFileChange} />
                            
                            <div className="flex-1 space-y-3">
                                <div>
                                    <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Name *</label>
                                    <input
                                        type="text"
                                        value={form.name}
                                        onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                                        className="mt-1 w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-4 py-2 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 transition-all"
                                        placeholder="Character name"
                                    />
                                </div>
                                <div>
                                    <button 
                                        onClick={openGalleryPicker}
                                        className="w-full text-xs font-semibold text-blue-400 bg-blue-500/10 hover:bg-blue-500/20 py-2 rounded-lg border border-blue-500/20 flex items-center justify-center gap-2 transition-colors"
                                    >
                                        <Images size={14} /> Import from Gallery
                                    </button>
                                </div>
                            </div>
                        </div>

                        {CHARACTER_FIELDS.filter(f => f.key !== 'name').map(field => (
                            <div key={field.key}>
                                <div className="flex items-center justify-between mb-1">
                                    <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">{field.label}</label>
                                    {field.key !== 'creator_notes' && (
                                        <button
                                            onClick={() => handleGenerateField(field.key)}
                                            className="px-2 py-1 bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded-md text-[10px] font-bold uppercase tracking-wider hover:bg-indigo-500/20 transition-colors flex items-center gap-1"
                                            title={`Auto-generate ${field.label}`}
                                        >
                                            <Sparkles size={12} /> Auto-Fill
                                        </button>
                                    )}
                                </div>
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
                            <div className="flex items-center justify-between mb-1">
                                <div>
                                    <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Visual Tags</label>
                                    <p className="text-[11px] text-gray-500">Tags for image generation (e.g., 1girl, blue hair, school uniform)</p>
                                </div>
                                <button
                                    onClick={() => handleGenerateField('visual_tags')}
                                    className="px-2 py-1 bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded-md text-[10px] font-bold uppercase tracking-wider hover:bg-indigo-500/20 transition-colors flex items-center gap-1"
                                    title="Auto-generate Visual Tags"
                                >
                                    <Sparkles size={12} /> Auto-Fill
                                </button>
                            </div>
                            <div className="flex flex-wrap gap-2 mb-2 mt-2">
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

                    {/* Gallery Picker Modal Overlay */}
                    <AnimatePresence>
                        {showGalleryPicker && (
                            <motion.div
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                                exit={{ opacity: 0 }}
                                className="absolute inset-0 bg-gray-900/95 z-50 flex flex-col rounded-xl overflow-hidden"
                            >
                                <div className="flex items-center justify-between p-4 border-b border-gray-700/50">
                                    <h3 className="font-semibold text-gray-200">Select Recent Image</h3>
                                    <button onClick={() => setShowGalleryPicker(false)} className="text-gray-500 hover:text-white"><X size={20} /></button>
                                </div>
                                <div className="flex-1 overflow-y-auto p-4">
                                    {loadingGallery ? (
                                        <div className="flex items-center justify-center h-full"><Loader2 className="animate-spin text-gray-500" size={32} /></div>
                                    ) : recentImages.length === 0 ? (
                                        <div className="text-center text-gray-500 py-10">No recent images found in output folder.</div>
                                    ) : (
                                        <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                                            {recentImages.map(img => (
                                                <button
                                                    key={img.relative_path || img.name}
                                                    onClick={() => handleSelectGalleryImage(img)}
                                                    className="aspect-square rounded-lg border border-gray-700 overflow-hidden hover:border-blue-500 transition-colors"
                                                >
                                                    <img src={img.preview} alt="" className="w-full h-full object-cover" />
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </motion.div>
            </div>
        </AnimatePresence>
    );
}

function CharacterCard({ character, onEdit, onDelete, onChat }) {
    const { data: collection } = useCharacterCollection(character.id);
    const imageCount = collection?.image_count || 0;
    const thumbnails = collection?.images?.slice(0, 4) || [];

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

            {imageCount > 0 && (
                <div className="mt-3">
                    <div className="flex items-center gap-1.5 mb-1.5">
                        <Images size={12} className="text-gray-500" />
                        <span className="text-[11px] text-gray-500">{imageCount} scene{imageCount !== 1 ? 's' : ''}</span>
                    </div>
                    <div className="grid grid-cols-4 gap-1">
                        {thumbnails.map((filename, idx) => (
                            <div key={idx} className="aspect-square rounded bg-gray-800/50 border border-white/5 overflow-hidden">
                                <img
                                    src={`/api/files/${filename}`}
                                    alt=""
                                    className="w-full h-full object-cover"
                                    loading="lazy"
                                    onError={(e) => { e.target.style.display = 'none'; }}
                                />
                            </div>
                        ))}
                    </div>
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
    const fileInputRef = useRef(null);

    const navigate = useNavigate();
    const setActiveChat = useWorldVaultStore(state => state.setActiveChat);

    const { data: characters = [], isLoading } = useCharacters();
    const createCharacter = useCreateCharacter();
    const updateCharacter = useUpdateCharacter();
    const deleteCharacter = useDeleteCharacter();
    const importCharacterCard = useImportCharacterCard();

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
        const { _avatarFile, ...payload } = form;
        if (editingCharacter) {
            return await updateCharacter.mutateAsync({ id: editingCharacter.id, ...payload });
        } else {
            return await createCharacter.mutateAsync(payload);
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

    const handleImportCard = (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        const formData = new FormData();
        formData.append('file', file);
        toast.promise(
            importCharacterCard.mutateAsync(formData),
            {
                loading: 'Importing character card...',
                success: (character) => `"${character.name}" imported successfully`,
                error: (err) => err?.response?.data?.detail || 'Failed to import card',
            }
        );
        e.target.value = '';
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
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept=".png"
                        className="hidden"
                        onChange={handleImportCard}
                    />
                    <button
                        onClick={() => fileInputRef.current?.click()}
                        disabled={importCharacterCard.isPending}
                        className="btn-secondary flex items-center gap-2 disabled:opacity-50"
                    >
                        {importCharacterCard.isPending ? <Loader2 size={18} className="animate-spin" /> : <Upload size={18} />}
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
