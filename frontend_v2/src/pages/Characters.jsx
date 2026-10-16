import React, { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    DndContext,
    PointerSensor,
    KeyboardSensor,
    useSensor,
    useSensors,
    closestCenter,
} from '@dnd-kit/core';
import {
    SortableContext,
    rectSortingStrategy,
    sortableKeyboardCoordinates,
    arrayMove,
} from '@dnd-kit/sortable';
import { Users, Plus, Upload, Search, X, Loader2, User, Images, Sparkles, Brain, LayoutGrid, Rows3, BookOpen } from 'lucide-react';
import toast from 'react-hot-toast';
import { useNavigate } from 'react-router-dom';
import { useCharacters, useCreateCharacter, useUpdateCharacter, useDeleteCharacter, useUploadAvatar, useCharacterCollections, useImportCharacterCard, useExportCharacterCard, getAvatarUrl, useAnimateCharacterAvatar, useReorderCharacters, useCloneCharacter, useLorebooks, useWorlds } from '../hooks/useWorldVault';
import { CARD_ACCEPT, cardExportFormatLabel } from '../api/characterCards';
import { useVoices } from '../hooks/useVoices';
import { useLLMJobResult } from '../hooks/useLLMJobResult';
import { SortableCharacterCard } from '../components/characters/CharacterCard';
import ModalOverlay from '../components/common/ModalOverlay';
import CharacterCardImportReport from '../components/characters/CharacterCardImportReport';
import { useWorldVaultStore } from '../store/worldVaultStore';
import useSettingsStore from '../store/settingsStore';
import EmptyState from '../components/EmptyState';
import { useConfirmation } from '../store/confirmationStore';
import filesApi from '../api/files';
import MemoriesPanel from '../components/chat/MemoriesPanel';
import RoleplayPageShell from '../components/RoleplayPageShell';
import { QueryErrorState } from '../components/common/QueryState';


const CHARACTER_FIELDS = [
    { key: 'name', label: 'Name', type: 'text', required: true, placeholder: 'Character name' },
    { key: 'description', label: 'Description', type: 'textarea', placeholder: 'A brief description of the character...' },
    { key: 'personality', label: 'Personality', type: 'textarea', placeholder: 'How does this character behave? Traits, quirks, mannerisms...' },
    { key: 'scenario', label: 'Scenario', type: 'textarea', placeholder: 'The situation or setting for this character...' },
    { key: 'first_mes', label: 'First Message', type: 'textarea', placeholder: 'The character\'s opening message (greeting)...' },
    { key: 'mes_example', label: 'Message Examples', type: 'textarea', placeholder: 'Example messages showing how the character speaks...' },
    { key: 'system_prompt', label: 'System Prompt', type: 'textarea', placeholder: 'Custom system prompt (leave empty to auto-generate from fields above)...' },
    { key: 'creator_notes', label: 'Creator Notes', type: 'textarea', placeholder: 'Notes about this character...' },
    { key: 'default_time', label: 'Default Story Time', type: 'text', placeholder: 'e.g. Night, Morning...' },
    { key: 'default_location', label: 'Default Location', type: 'text', placeholder: 'e.g. Tavern, Castle...' },
];

const DEFAULT_FORM = {
    name: '', description: '', personality: '', scenario: '',
    first_mes: '', mes_example: '', system_prompt: '', creator_notes: '',
    default_time: '', default_location: '',
    visual_tags: [], lora_triggers: [], voice_profile: '', lorebook_ids: [],
    world_id: '',
};

// Above this many books the list stops being scannable and a filter earns its
// space. Below it, a search box is one more control between the user and the
// thing they came to do.
const LOREBOOK_SEARCH_THRESHOLD = 6;

export function CharacterModal({ isOpen, onClose, character, onSave, activeTab: activeTabProp, onTabChange }) {
    // `activeTab`/`onTabChange` are optional: call sites that only need the
    // details form (e.g. StorySandbox's context panel) must not crash on a
    // missing onTabChange.
    const [internalTab, setInternalTab] = useState('details');
    const activeTab = activeTabProp ?? internalTab;
    const handleTabChange = (tab) => {
        setInternalTab(tab);
        onTabChange?.(tab);
    };
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
                default_time: character.default_time || '',
                default_location: character.default_location || '',
                visual_tags: character.visual_tags || [],
                lora_triggers: character.lora_triggers || [],
                voice_profile: character.voice_profile || '',
                voice_model_id: character.voice_model_id || null,
                lorebook_ids: Array.isArray(character.lorebook_ids) ? character.lorebook_ids : [],
                world_id: character.world_id || '',
            };
        }
        return { ...DEFAULT_FORM };
    });
    const [visualTagInput, setVisualTagInput] = useState('');
    const [loraTagInput, setLoraTagInput] = useState('');
    const [lorebookSearch, setLorebookSearch] = useState('');
    const [saving, setSaving] = useState(false);

    const { data: voices = [] } = useVoices();
    const { data: lorebooks = [] } = useLorebooks();
    const { data: worlds = [] } = useWorlds();

    const isEditing = !!character;
    
    const uploadAvatarMutation = useUploadAvatar();
    const animateAvatarMutation = useAnimateCharacterAvatar();
    const avatarInputRef = React.useRef(null);
    const [previewUrl, setPreviewUrl] = useState(null);
    const previewUrlRef = useRef(null);
    const runLLMJob = useLLMJobResult();

    const setPreview = (url) => {
        if (previewUrlRef.current) {
            URL.revokeObjectURL(previewUrlRef.current);
        }
        // Keep the ref in step with the state, including when clearing it: the
        // old code assigned `null` without revoking, so the unmount cleanup saw
        // `null` and the blob stayed live for the page's lifetime.
        previewUrlRef.current = url;
        setPreviewUrl(url);
    };

    React.useEffect(() => {
        return () => {
            if (previewUrlRef.current) {
                URL.revokeObjectURL(previewUrlRef.current);
                previewUrlRef.current = null;
            }
        };
    }, []);

    const handleFileChange = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        
        // Show preview immediately
        setPreview(URL.createObjectURL(file));

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
            const res = await filesApi.list({ directory: 'output', limit: 12 });
            setRecentImages(res.files || []);
        } catch {
            toast.error('Failed to load recent images');
        }
        setLoadingGallery(false);
    };

    const handleSelectGalleryImage = async (img) => {
        try {
            // Fetch metadata to populate fields
            const metaRes = await filesApi.batchMetadata([img.relative_path]);
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
            
            setPreview(URL.createObjectURL(file));
            
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
            const result = await onSave({
                ...form,
                world_id: form.world_id || null,
            });
            const savedCharId = isEditing ? character.id : (result?.id || result?.data?.id);
            
            // Upload avatar if a file was selected during creation
            if (!isEditing && form._avatarFile && savedCharId) {
                try {
                    await uploadAvatarMutation.mutateAsync({ characterId: savedCharId, file: form._avatarFile });
                } catch {
                    toast.error("Avatar upload failed after creation");
                }
            }
            
            toast.success(isEditing ? 'Character updated' : 'Character created');
            onClose();
            setPreview(null);
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

    const toggleLorebook = (lorebookId) => {
        setForm(f => ({
            ...f,
            lorebook_ids: f.lorebook_ids.includes(lorebookId)
                ? f.lorebook_ids.filter(id => id !== lorebookId)
                : [...f.lorebook_ids, lorebookId],
        }));
    };

    // A book attached to a character but no longer in the vault would otherwise
    // be invisible: it has no row to show and no name to search for, so the
    // count would read "1 attached" with nothing in the list. Shown by id so
    // the user can un-attach the dangling reference.
    const danglingLorebookIds = form.lorebook_ids.filter(
        id => id !== character?.embedded_lorebook_id && !lorebooks.some(lb => lb.id === id)
    );

    // The card's embedded book is excluded from the attachable list rather
    // than shown twice. It is ALREADY injected into every chat with this
    // character (`chat_utils.link_embedded_lorebook`), so offering to attach
    // it is redundant — and showing the same book once as an untouchable amber
    // row and once as a checkbox is the exact confusion the row exists to
    // prevent.
    const embeddedId = character?.embedded_lorebook_id || null;
    const editableLorebooks = useMemo(
        () => lorebooks.filter(lb => lb.id !== embeddedId),
        [lorebooks, embeddedId]
    );

    const visibleLorebooks = useMemo(() => {
        const q = lorebookSearch.trim().toLowerCase();
        // Attached books are never filtered out, only ranked below the matches.
        // Hiding a book the character is already attached to would leave the
        // count reading "2 attached" with one of them unreachable, and the only
        // way to drop it would be to clear the search first.
        const pool = q
            ? editableLorebooks.filter(
                lb => (lb.name || '').toLowerCase().includes(q) || form.lorebook_ids.includes(lb.id)
            )
            : editableLorebooks;
        return [
            ...pool.filter(lb => form.lorebook_ids.includes(lb.id)),
            ...pool.filter(lb => !form.lorebook_ids.includes(lb.id)),
        ];
    }, [editableLorebooks, lorebookSearch, form.lorebook_ids]);

    const showLorebookSearch = editableLorebooks.length > LOREBOOK_SEARCH_THRESHOLD;
    const embeddedLorebook = useMemo(
        () => lorebooks.find(lb => lb.id === embeddedId) || null,
        [lorebooks, embeddedId]
    );

    const settings = useSettingsStore(s => s.settings);

    const handleGenerateField = async (fieldKey) => {
        if (!form.name.trim() && !form.description.trim()) {
            toast.error('Provide at least a name or short description first!');
            return;
        }
        
        let promptKey = '';
        const aiSettings = settings.ai || {};
        switch(fieldKey) {
            case 'description': promptKey = 'charGenDescriptionPrompt'; break;
            case 'personality': promptKey = 'charGenPersonalityPrompt'; break;
            case 'scenario': promptKey = 'charGenScenarioPrompt'; break;
            case 'first_mes': promptKey = 'charGenFirstMesPrompt'; break;
            case 'mes_example': promptKey = 'charGenMesExamplePrompt'; break;
            case 'system_prompt': promptKey = 'charGenSystemPromptPrompt'; break;
            case 'visual_tags': promptKey = 'charGenVisualTagsPrompt'; break;
            default: return;
        }
        const sysPrompt = aiSettings[promptKey] || '';
        
        let context = `Name: ${form.name}\n`;
        if (form.description && fieldKey !== 'description') context += `Description: ${form.description}\n`;
        if (form.personality && fieldKey !== 'personality') context += `Personality: ${form.personality}\n`;
        if (form.scenario && fieldKey !== 'scenario') context += `Scenario: ${form.scenario}\n`;
        
        toast(`Generating ${fieldKey}...`, { icon: '🤖' });
        try {
            const { text, cancelled } = await runLLMJob({
                workflow: {
                    messages: [
                        { role: "system", content: sysPrompt },
                        { role: "user", content: context }
                    ]
                }
            });
            if (cancelled || !text) {
                if (!cancelled) toast.error('Generation failed');
                return;
            }
            try {
                const raw = text.trim();
                if (fieldKey === 'visual_tags') {
                    const tags = raw.split(',').map(s => s.trim()).filter(Boolean);
                    setForm(f => ({ ...f, visual_tags: [...new Set([...f.visual_tags, ...tags])] }));
                } else {
                    setForm(f => ({ ...f, [fieldKey]: raw }));
                }
                toast.success('Generated field!');
            } catch {
                toast.error('Failed to parse AI output');
            }
        } catch {
            toast.error('Failed to generate profile');
        }
    };

    const handleEnrichProfile = async () => {
        if (!form.name.trim() && !form.description.trim()) {
            toast.error('Provide at least a name or description first!');
            return;
        }

        const sysPrompt = settings.ai?.charGenEnrichPrompt || 'You are an expert character creator. Read the provided character details and fill in ALL missing fields to enrich the character profile. Output MUST be valid JSON matching exactly these keys: "description", "personality", "scenario", "first_mes", "mes_example", "default_time", "default_location". Do not include markdown code blocks, just raw JSON.';
        let context = `Name: ${form.name}\n`;
        if (form.description) context += `Description: ${form.description}\n`;
        if (form.personality) context += `Personality: ${form.personality}\n`;
        if (form.scenario) context += `Scenario: ${form.scenario}\n`;
        if (form.first_mes) context += `First Message: ${form.first_mes}\n`;
        
        const tId = toast('Enriching profile... (This may take a minute)', { icon: '🤖' });
        try {
            const { text, cancelled } = await runLLMJob({
                workflow: {
                    messages: [
                        { role: "system", content: sysPrompt },
                        { role: "user", content: context }
                    ]
                },
                maxPolls: 180,
            });
            if (cancelled) return;
            toast.dismiss(tId);

            if (!text) {
                toast.error('Enrichment failed or timed out');
                return;
            }

            const raw = text.trim();

            // Find JSON block
            const jsonMatch = raw.match(/\{[\s\S]*\}/);
            if (jsonMatch) {
                try {
                    const parsed = JSON.parse(jsonMatch[0]);
                    setForm(f => ({
                        ...f,
                        description: parsed.description || f.description,
                        personality: parsed.personality || f.personality,
                        scenario: parsed.scenario || f.scenario,
                        first_mes: parsed.first_mes || f.first_mes,
                        mes_example: parsed.mes_example || f.mes_example,
                        default_time: parsed.default_time || f.default_time,
                        default_location: parsed.default_location || f.default_location
                    }));
                    toast.success('Profile Enriched!');
                } catch {
                    toast.error('Failed to parse AI output');
                }
            } else {
                toast.error('Failed to find JSON in AI output');
            }
        } catch {
            toast.dismiss(tId);
            toast.error('Failed to enrich profile');
        }
    };

    // Mounted unconditionally by the page with an `isOpen` prop, so the open
    // state goes to the overlay: a closed editor must not keep a live Escape
    // listener, and the early `return null` this replaces made the
    // AnimatePresence wrapper inert.
    return (
        <AnimatePresence>
            <ModalOverlay
                key="character-editor-overlay"
                isOpen={!!isOpen}
                onClose={onClose}
                className="z-[90] bg-black/80 backdrop-blur-sm"
            >
                <motion.div
                    role="dialog"
                    aria-modal="true"
                    aria-label={isEditing ? 'Edit Character' : 'Create Character'}
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    className="bg-gray-900 rounded-xl border border-gray-700 w-full max-w-2xl max-h-[85vh] shadow-2xl flex flex-col"
                    onClick={e => e.stopPropagation()}
                >
                    <div className="shrink-0">
                        {/* Modal title + actions */}
                        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700/50">
                            <div className="flex items-center gap-3">
                                <h2 className="text-lg font-bold text-gray-100">{isEditing ? 'Edit Character' : 'Create Character'}</h2>
                                {activeTab === 'details' && (
                                    <button 
                                        onClick={handleEnrichProfile}
                                        className="ml-2 flex items-center gap-1.5 px-3 py-1.5 text-xs bg-yellow-500/20 text-yellow-300 rounded-lg hover:bg-yellow-500/30 transition-colors border border-yellow-500/30"
                                        title="Auto-fill missing information using AI"
                                    >
                                        <Sparkles size={14} /> Enrich
                                    </button>
                                )}
                            </div>
                            <button onClick={onClose} aria-label="Close character editor" className="text-gray-500 hover:text-white transition-colors"><X size={20} /></button>
                        </div>

                        {/* Tab bar (only visible when editing) */}
                        {isEditing && (
                            <div className="flex items-center gap-1 px-6 py-2 border-b border-gray-700/30 bg-gray-900/40">
                                <button
                                    type="button"
                                    onClick={() => handleTabChange('details')}
                                    className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                                        activeTab === 'details'
                                            ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                                            : 'text-gray-500 hover:text-gray-300 hover:bg-white/5'
                                    }`}
                                >
                                    <User size={12} /> Details
                                </button>
                                <button
                                    type="button"
                                    onClick={() => handleTabChange('memories')}
                                    className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                                        activeTab === 'memories'
                                            ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30'
                                            : 'text-gray-500 hover:text-gray-300 hover:bg-white/5'
                                    }`}
                                >
                                    <Brain size={12} /> Memories
                                </button>
                            </div>
                        )}
                    </div>

                    {/* Tab: Memories */}
                    {activeTab === 'memories' && isEditing && (
                        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
                            <MemoriesPanel characterId={character.id} />
                        </div>
                    )}

                    {/* Tab: Details (always shown for new characters; toggled for editing) */}
                    <div className={`flex-1 overflow-y-auto p-6 space-y-5 custom-scrollbar ${
                        activeTab === 'memories' ? 'hidden' : ''
                    }`}>
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
                            <input type="file" ref={avatarInputRef} aria-label="Character avatar image" className="hidden" accept="image/*" onChange={handleFileChange} />
                            
                            <div className="flex-1 space-y-3">
                                <div>
                                    <label htmlFor="character-form-name" className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Name *</label>
                                    <input
                                        id="character-form-name"
                                        type="text"
                                        value={form.name}
                                        onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                                        className="mt-1 w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-4 py-2 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 transition-all"
                                        placeholder="Character name"
                                    />
                                </div>
                                <div className="flex items-center gap-2">
                                    <button 
                                        onClick={openGalleryPicker}
                                        className="flex-1 text-xs font-semibold text-blue-400 bg-blue-500/10 hover:bg-blue-500/20 py-2 rounded-lg border border-blue-500/20 flex items-center justify-center gap-2 transition-colors"
                                    >
                                        <Images size={14} /> Import from Gallery
                                    </button>
                                    {isEditing && character.has_avatar && (
                                        <button 
                                            onClick={() => {
                                                toast.promise(
                                                    animateAvatarMutation.mutateAsync({
                                                        characterId: character.id,
                                                        prompt: `portrait of ${character.name}, ${character.description}, dynamic, motion, highly detailed`
                                                    }),
                                                    {
                                                        loading: 'Enqueueing animation job...',
                                                        success: 'Avatar animation job queued! Check Active Jobs.',
                                                        error: 'Failed to queue animation'
                                                    }
                                                );
                                            }}
                                            className="flex-1 text-xs font-semibold text-amber-400 bg-amber-500/10 hover:bg-amber-500/20 py-2 rounded-lg border border-amber-500/20 flex items-center justify-center gap-2 transition-colors"
                                        >
                                            <Sparkles size={14} /> Animate Avatar
                                        </button>
                                    )}
                                </div>
                            </div>
                        </div>

                        {CHARACTER_FIELDS.filter(f => f.key !== 'name').map(field => (
                            <div key={field.key}>
                                <div className="flex items-center justify-between mb-1">
                                    <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider">{field.label}</div>
                                    {field.key !== 'creator_notes' && field.key !== 'default_time' && field.key !== 'default_location' && (
                                        <button
                                            onClick={() => handleGenerateField(field.key)}
                                            className="px-2 py-1 bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded-md text-xs font-bold uppercase tracking-wider hover:bg-indigo-500/20 transition-colors flex items-center gap-1"
                                            title={`Auto-generate ${field.label}`}
                                        >
                                            <Sparkles size={12} /> Auto-Fill
                                        </button>
                                    )}
                                </div>
                                {field.type === 'textarea' ? (
                                    <textarea
                                        value={form[field.key]}
                                        onChange={e => setForm(f => ({ ...f, [field.key]: e.target.value }))}
                                        className="mt-1 w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-4 py-2 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 transition-all resize-none"
                                        rows={field.key === 'system_prompt' ? 3 : 4}
                                        placeholder={field.placeholder}
                                    />
                                ) : (
                                    <input
                                        type="text"
                                        value={form[field.key]}
                                        onChange={e => setForm(f => ({ ...f, [field.key]: e.target.value }))}
                                        className="mt-1 w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-4 py-2 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 transition-all"
                                        placeholder={field.placeholder}
                                    />
                                )}
                            </div>
                        ))}

                        {/* Visual Tags */}
                        <div>
                            <div className="flex items-center justify-between mb-1">
                                <div>
                                    <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Visual Tags</div>
                                    <p className="text-2xs text-gray-500">Tags for image generation (e.g., 1girl, blue hair, school uniform)</p>
                                </div>
                                <button
                                    onClick={() => handleGenerateField('visual_tags')}
                                    className="px-2 py-1 bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded-md text-xs font-bold uppercase tracking-wider hover:bg-indigo-500/20 transition-colors flex items-center gap-1"
                                    title="Auto-generate Visual Tags"
                                >
                                    <Sparkles size={12} /> Auto-Fill
                                </button>
                            </div>
                            <div className="flex flex-wrap gap-2 mb-2 mt-2">
                                {form.visual_tags.map((tag, idx) => (
                                    <span key={idx} className="px-2 py-1 text-xs bg-purple-500/20 text-purple-300 rounded-full border border-purple-500/30 flex items-center gap-1">
                                        {tag}
                                        <button onClick={() => removeTag('visual_tags', idx)} aria-label={`Remove visual tag ${tag}`} className="text-purple-400 hover:text-white ml-1"><X size={12} /></button>
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
                            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider">LoRA Triggers</div>
                            <p className="text-2xs text-gray-500 mb-2">LoRA trigger words for this character</p>
                            <div className="flex flex-wrap gap-2 mb-2">
                                {form.lora_triggers.map((tag, idx) => (
                                    <span key={idx} className="px-2 py-1 text-xs bg-blue-500/20 text-blue-300 rounded-full border border-blue-500/30 flex items-center gap-1">
                                        {tag}
                                        <button onClick={() => removeTag('lora_triggers', idx)} aria-label={`Remove LoRA trigger ${tag}`} className="text-blue-400 hover:text-white ml-1"><X size={12} /></button>
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

                        {/* Lorebooks */}
                        <div data-testid="character-lorebooks">
                            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Lorebooks</div>
                            <p className="text-2xs text-gray-500 mb-2">
                                Library books this character draws on. They are attached to every chat and story
                                this character is in, so you set them once instead of per conversation.
                            </p>

                            {/* The embedded card book is a DIFFERENT relationship and the
                                one place on this form a user is most likely to be confused,
                                so it is named and excluded rather than silently omitted. */}
                            {embeddedLorebook && (
                                <div
                                    className="flex items-center gap-2 px-2.5 py-2 mb-2 rounded-lg bg-amber-500/10 border border-amber-500/25"
                                    data-testid="character-embedded-lorebook"
                                >
                                    <BookOpen size={12} className="text-amber-300 shrink-0" aria-hidden="true" />
                                    <span className="text-2xs text-amber-200 truncate">{embeddedLorebook.name}</span>
                                    <span className="text-2xs text-amber-300/70 ml-auto shrink-0">
                                        Card lorebook — belongs to the imported card
                                    </span>
                                </div>
                            )}

                            {showLorebookSearch && (
                                <div className="relative mb-2">
                                    <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" aria-hidden="true" />
                                    <input
                                        type="text"
                                        value={lorebookSearch}
                                        onChange={e => setLorebookSearch(e.target.value)}
                                        className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg pl-7 pr-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                                        placeholder="Search lorebooks..."
                                        aria-label="Search lorebooks"
                                    />
                                </div>
                            )}

                            {editableLorebooks.length === 0 && danglingLorebookIds.length === 0 ? (
                                <p className="text-2xs text-gray-600" data-testid="character-lorebooks-empty">
                                    {embeddedLorebook
                                        ? 'This character’s card is the only lorebook attached to it.'
                                        : 'No lorebooks in the vault yet.'}
                                </p>
                            ) : (
                                <ul className="max-h-40 overflow-y-auto custom-scrollbar rounded-lg border border-gray-700/40 divide-y divide-white/5">
                                    {danglingLorebookIds.map(id => (
                                        <li key={`dangling-${id}`}>
                                            <label className="flex items-center gap-2 px-2.5 py-1.5 cursor-pointer hover:bg-white/5 transition-colors">
                                                <input
                                                    type="checkbox"
                                                    checked
                                                    onChange={() => toggleLorebook(id)}
                                                    className="accent-indigo-500 shrink-0"
                                                    aria-label={`Detach missing lorebook ${id}`}
                                                />
                                                <span className="text-xs text-gray-500 truncate flex-1">{id}</span>
                                                <span className="text-2xs text-red-300/80 shrink-0">missing — untick to drop</span>
                                            </label>
                                        </li>
                                    ))}
                                    {visibleLorebooks.map(lb => {
                                        const attached = form.lorebook_ids.includes(lb.id);
                                        return (
                                            <li key={lb.id}>
                                                <label className="flex items-center gap-2 px-2.5 py-1.5 cursor-pointer hover:bg-white/5 transition-colors">
                                                    <input
                                                        type="checkbox"
                                                        checked={attached}
                                                        onChange={() => toggleLorebook(lb.id)}
                                                        className="accent-indigo-500 shrink-0"
                                                        aria-label={`Attach ${lb.name}`}
                                                    />
                                                    <span className="text-xs text-gray-200 truncate flex-1">{lb.name}</span>
                                                    {attached && (
                                                        <span className="text-2xs text-indigo-300 shrink-0">attached</span>
                                                    )}
                                                </label>
                                            </li>
                                        );
                                    })}
                                    {visibleLorebooks.length === 0 && danglingLorebookIds.length === 0 && (
                                        <li className="px-2.5 py-1.5 text-2xs text-gray-600">
                                            No lorebook matches &quot;{lorebookSearch}&quot;.
                                        </li>
                                    )}
                                </ul>
                            )}

                            {form.lorebook_ids.length > 0 && (
                                <p className="text-2xs text-gray-500 mt-2" data-testid="character-lorebooks-count">
                                    {form.lorebook_ids.length} {form.lorebook_ids.length === 1 ? 'lorebook' : 'lorebooks'} attached
                                </p>
                            )}
                        </div>

                        {/* World Assignment */}
                        <div>
                            <label htmlFor="character-form-world" className="text-xs font-semibold text-gray-400 uppercase tracking-wider">World (Optional)</label>
                            <select
                                id="character-form-world"
                                value={form.world_id || ''}
                                onChange={e => setForm(f => ({ ...f, world_id: e.target.value }))}
                                className="mt-1 w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-gray-200 focus:outline-none focus:border-blue-500/50 transition-all"
                            >
                                <option value="">No World (Global)</option>
                                {worlds.map(w => (
                                    <option key={w.id} value={w.id}>{w.name}</option>
                                ))}
                            </select>
                        </div>

                        {/* Voice Profile */}
                        <div>
                            <label htmlFor="character-form-voice-model" className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Voice Model</label>
                            <select
                                id="character-form-voice-model"
                                value={form.voice_model_id || ''}
                                onChange={e => {
                                    const v = voices.find(x => String(x.id) === String(e.target.value));
                                    setForm(f => ({
                                        ...f,
                                        voice_model_id: v?.id || null,
                                        voice_profile: v?.voice_profile || v?.name || form.voice_profile,
                                    }));
                                }}
                                className="mt-1 w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-gray-200 focus:outline-none focus:border-blue-500/50 transition-all"
                            >
                                <option value="" disabled>Choose a voice (optional)</option>
                                {voices.map(v => (
                                    <option key={v.id} value={v.id}>
                                        {v.name}{v.voice_profile ? ` — ${v.voice_profile}` : ''}
                                    </option>
                                ))}
                            </select>
                            <input
                                type="text"
                                value={form.voice_profile}
                                onChange={e => setForm(f => ({ ...f, voice_profile: e.target.value }))}
                                className="mt-2 w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-1.5 text-xs text-gray-400 placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                                placeholder="Voice profile name override (used by name-based resolution)"
                            />
                        </div>
                    </div>

                    {/* Footer: hide Save/Cancel on the Memories tab */}
                    {activeTab !== 'memories' && (
                    <div className="flex gap-3 px-6 py-4 border-t border-gray-700/50 shrink-0">
                        <button onClick={onClose} className="flex-1 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-medium transition-colors">Cancel</button>
                        <button onClick={handleSave} disabled={saving} className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium transition-colors shadow-lg shadow-blue-900/20 flex items-center justify-center gap-2">
                            {saving ? <Loader2 size={16} className="animate-spin" /> : null}
                            {isEditing ? 'Update' : 'Create'}
                        </button>
                    </div>
                    )}

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
                                    <button onClick={() => setShowGalleryPicker(false)} aria-label="Close recent image picker" className="text-gray-500 hover:text-white"><X size={20} /></button>
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
                                                    <img src={img.preview} alt={img.name || img.relative_path} className="w-full h-full object-cover" />
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </motion.div>
            </ModalOverlay>
        </AnimatePresence>
    );
}

export default function Characters() {
    const [searchQuery, setSearchQuery] = useState('');
    // 'comfortable' | 'compact'. Carried over from the retired Avatar Gallery,
    // which was this grid with a density switch and the edit actions removed.
    const [density, setDensity] = useState('comfortable');
    const [modalOpen, setModalOpen] = useState(false);
    const [editingCharacter, setEditingCharacter] = useState(null);
    const [activeTab, setActiveTab] = useState('details');
    const [importReport, setImportReport] = useState(null);
    const fileInputRef = useRef(null);
    const [cloningId, setCloningId] = useState(null);

    const navigate = useNavigate();
    const setActiveChat = useWorldVaultStore(state => state.setActiveChat);
    const { confirm } = useConfirmation();

    // `isError` is load-bearing. Without it a failed fetch rendered
    // "You haven't created any characters yet" with a working Create button,
    // next to a vault that already had characters — and clicking it made a
    // duplicate. See components/common/QueryState.jsx.
    const { data: characters = [], isLoading, isError, error, refetch } = useCharacters();
    const { data: characterCollections } = useCharacterCollections(characters.map(c => c.id));
    const createCharacter = useCreateCharacter();
    const updateCharacter = useUpdateCharacter();
    const deleteCharacter = useDeleteCharacter();
    const importCharacterCard = useImportCharacterCard();
    const exportCharacterCard = useExportCharacterCard();
    const reorderCharacters = useReorderCharacters();
    const cloneCharacter = useCloneCharacter();

    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
    );

    const characterIndex = useMemo(() => {
        const m = new Map();
        characters.forEach((c, i) => m.set(c.id, i));
        return m;
    }, [characters]);

    const handleDragEnd = useCallback((event) => {
        const { active, over } = event;
        if (!over || active.id === over.id) return;
        const oldIndex = characterIndex.get(String(active.id));
        const newIndex = characterIndex.get(String(over.id));
        if (oldIndex == null || newIndex == null || oldIndex === newIndex) return;
        const reordered = arrayMove(characters, oldIndex, newIndex);
        reorderCharacters.mutate(reordered.map(c => c.id));
    }, [characterIndex, characters, reorderCharacters]);

    // Handle URL hash deep-link: /characters#char-{id}
    const deepLinkCharRef = useRef(null);
    useEffect(() => {
        const hash = window.location.hash;
        if (!hash.startsWith('#char-')) return;
        const charId = hash.slice(6);
        if (characters.length === 0) return;
        const targetChar = characters.find(c => c.id === charId);
        if (!targetChar) return;
        if (editingCharacter?.id === charId) return;
        deepLinkCharRef.current = targetChar;
        setEditingCharacter(deepLinkCharRef.current);
        setModalOpen(true);
        window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    }, [characters, editingCharacter?.id]);

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

    const handleDelete = async (char) => {
        const ok = await confirm({
            title: 'Delete Character',
            message: `Are you sure you want to delete "${char.name}"? This cannot be undone.`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            await deleteCharacter.mutateAsync(char.id);
            toast.success(`"${char.name}" deleted`);
        } catch {
            toast.error('Failed to delete character');
        }
    };

    const handleStartChat = async (character) => {
        setActiveChat(null);
        navigate('/chat', { state: { characterId: character.id } });
        toast(`Starting chat with ${character.name}...`, { icon: '💬' });
    };

    const handleImportCard = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;

        try {
            const { character, compatibility } = await importCharacterCard.mutateAsync(file);
            setImportReport({ character, compatibility, filename: file.name });
            toast.success(`"${character?.name || file.name}" imported`);
        } catch (err) {
            toast.error(err?.data?.detail || err?.message || 'Failed to import card');
        }
    };

    const handleExportCard = async (character, format) => {
        try {
            const { filename } = await exportCharacterCard.mutateAsync({ character, format });
            toast.success(`Exporting "${character.name}" as ${cardExportFormatLabel(format)}`, { icon: '📤' });
            return filename;
        } catch {
            toast.error('Failed to export character card');
            return null;
        }
    };

    const handleCloneCharacter = async (character) => {
        if (cloningId) return;
        setCloningId(character.id);
        try {
            const clone = await cloneCharacter.mutateAsync(character.id);
            toast.success(`"${character.name}" cloned as "${clone.name}"`, { icon: '🧬' });
        } catch {
            toast.error('Failed to clone character');
        } finally {
            setCloningId(null);
        }
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
        <RoleplayPageShell
            title="Character Vault"
            description="Manage your roleplay characters. Import SillyTavern V2/V3 PNG or JSON cards, or create new ones from scratch."
            icon={Users}
            maxWidth="max-w-none"
            className="flex h-full flex-col"
            actions={
                <>
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept={CARD_ACCEPT}
                        title="Import a SillyTavern card (.png or .json)"
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
                </>
            }
        >

            {/* Search Bar */}
            <div className="glass-panel p-4 mb-6 flex flex-wrap gap-4 items-center">
                <div className="relative flex-1 min-w-[200px]">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
                    <input 
                        type="text" 
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        aria-label="Search characters" placeholder="Search characters by name, tags, or description..." 
                        className="w-full bg-gray-900/50 border border-gray-700/50 rounded-lg pl-10 pr-4 py-2 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50 transition-all"
                    />
                </div>
                <div className="flex items-center gap-3">
                    <div className="text-sm text-gray-500">
                        {filteredCharacters.length} character{filteredCharacters.length !== 1 ? 's' : ''}
                    </div>
                    {/* Density toggle, the one capability the Avatar Gallery had
                        that this page did not. */}
                    <div className="flex items-center gap-1 rounded-lg bg-gray-900/50 border border-gray-700/50 p-0.5">
                        {['comfortable', 'compact'].map((mode) => (
                            <button
                                key={mode}
                                onClick={() => setDensity(mode)}
                                aria-pressed={density === mode}
                                title={mode === 'compact' ? 'Compact grid' : 'Comfortable grid'}
                                className={`p-1.5 rounded-md transition-colors ${density === mode
                                    ? 'bg-blue-500/20 text-blue-300'
                                    : 'text-gray-500 hover:text-gray-300'}`}
                            >
                                {mode === 'compact'
                                    ? <LayoutGrid size={14} aria-hidden="true" />
                                    : <Rows3 size={14} aria-hidden="true" />}
                            </button>
                        ))}
                    </div>
                </div>
            </div>

            {/* Character Grid */}
            <div className="flex-1 rounded-xl overflow-y-auto custom-scrollbar min-h-0">
                {isLoading ? (
                    <div className="flex items-center justify-center p-12">
                        <Loader2 className="animate-spin text-gray-500" size={32} />
                    </div>
                ) : isError ? (
                    <QueryErrorState noun="characters" error={error} onRetry={refetch} className="m-2" />
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
                    <DndContext
                        sensors={sensors}
                        collisionDetection={closestCenter}
                        onDragEnd={handleDragEnd}
                    >
                        <SortableContext
                            items={filteredCharacters.map(c => c.id)}
                            strategy={rectSortingStrategy}
                        >
                            {/* Density toggle, folded in from the retired Avatar
                                Gallery. That page was a second rendering of this
                                grid using the same `useCharacters()` and the same
                                `CharacterCard`, with the edit actions stripped off;
                                its only capability this lacked was a denser
                                layout. Its `visual_tags` search was NOT unique —
                                `filteredCharacters` below already matches
                                `visual_tags`. */}
                            <div className={density === 'compact'
                                ? 'grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6 gap-3'
                                : 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4'}>
                                {filteredCharacters.map(character => (
                                    <SortableCharacterCard
                                        key={character.id}
                                        character={character}
                                        collection={characterCollections?.[character.id]}
                                        onChat={handleStartChat}
                                        actions={{
                                            onEdit: openEdit,
                                            onDelete: handleDelete,
                                            onExport: handleExportCard,
                                            onClone: handleCloneCharacter,
                                            isCloning: cloningId === character.id,
                                        }}
                                    />
                                ))}
                            </div>
                        </SortableContext>
                    </DndContext>
                )}
            </div>

            {/* Character Modal */}
            <CharacterModal
                key={editingCharacter?.id || 'new'}
                isOpen={modalOpen}
                onClose={() => { setModalOpen(false); setEditingCharacter(null); }}
                character={editingCharacter}
                onSave={handleSave}
                activeTab={activeTab}
                onTabChange={setActiveTab}
            />

            {/* Post-import compatibility report */}
            {importReport && (
                <CharacterCardImportReport
                    character={importReport.character}
                    compatibility={importReport.compatibility}
                    filename={importReport.filename}
                    onClose={() => setImportReport(null)}
                    onEdit={(character) => {
                        setImportReport(null);
                        if (character) openEdit(character);
                    }}
                    onChat={(character) => {
                        setImportReport(null);
                        if (character) handleStartChat(character);
                    }}
                />
            )}

        </RoleplayPageShell>
    );
}
