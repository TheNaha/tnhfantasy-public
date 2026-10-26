import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Edit3, Trash2, Play, Volume2, FileText, AlertCircle, Wand2, Loader2, Sparkles, X, Zap } from 'lucide-react';
import toast from 'react-hot-toast';
import { useQueryClient } from '@tanstack/react-query';
import {
    useVoices,
    useCreateVoice,
    useUpdateVoice,
    useDeleteVoice,
    useVoicePreview,
    useDesignVoice,
    useVoicePresets,
    useWorlds,
} from '../hooks/useWorldVault';
import { useJobStatus } from '../hooks/useJobStatus';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { assetUrl } from '../utils/assetUrl';
import EmptyState from '../components/EmptyState';
import FormInput from '../components/common/FormInput';
import ModalOverlay from '../components/common/ModalOverlay';
import { useConfirmation } from '../store/confirmationStore';
import RoleplayPageShell from '../components/RoleplayPageShell';
import { QueryErrorState } from '../components/common/QueryState';

const TYPE_OPTIONS = [
    { value: 'qwen3_tts', label: 'Qwen3-TTS (Design)' },
    { value: 'qwen3_preset', label: 'Qwen3-TTS (Preset)' },
    { value: 'clone', label: 'Voice Clone' },
];

export default function Voices() {
    const [editingId, setEditingId] = useState(null);
    const [showCreate, setShowCreate] = useState(false);
    const [showDesign, setShowDesign] = useState(false);
    const [formData, setFormData] = useState({});
    const [designForm, setDesignForm] = useState({
        name: '',
        description: '',
        sample_text: '',
        language: 'en',
    });
    const [previewLoading, setPreviewLoading] = useState(false);
    const [previewJobId, setPreviewJobId] = useState(null);
    const queryClient = useQueryClient();

    // See components/common/QueryState.jsx — a failed fetch used to render
    // "No voice models yet" next to a vault that already had one.
    const { data: voices = [], isLoading, isError, error, refetch } = useVoices();
    const { data: worlds = [] } = useWorlds();
    const { data: presets = [] } = useVoicePresets();
    const { mutate: createVoice } = useCreateVoice();
    const { mutate: updateVoice } = useUpdateVoice();
    const { mutate: deleteVoice } = useDeleteVoice();
    const { mutateAsync: previewVoice } = useVoicePreview();
    const { mutateAsync: designVoice, isPending: isDesigning } = useDesignVoice();
    const { confirm } = useConfirmation();

    const { data: previewJob } = useJobStatus(previewJobId, { enabled: !!previewJobId });

    useEffect(() => {
        if (!previewJob) return;
        if (previewJob.status === 'completed') {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.VOICES) });
            setPreviewJobId(null);
        } else if (['failed', 'error', 'cancelled'].includes(previewJob.status)) {
            toast.error('Voice preview generation failed');
            setPreviewJobId(null);
        }
    }, [previewJob, queryClient]);

    const handleCreate = () => {
        if (!formData.name) {
            toast.error('Name is required');
            return;
        }
        const payload = { ...formData };
        if ('world_id' in payload) payload.world_id = payload.world_id || null;
        createVoice(payload, {
            onSuccess: () => {
                toast.success('Voice model created');
                setShowCreate(false);
                setFormData({});
            },
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const handleUpdate = () => {
        const payload = { id: editingId, ...formData };
        if ('world_id' in payload) payload.world_id = payload.world_id || null;
        updateVoice(payload, {
            onSuccess: () => {
                toast.success('Voice model updated');
                setEditingId(null);
                setFormData({});
            },
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const handleDelete = async (id, name) => {
        const ok = await confirm({
            title: 'Delete Voice Model',
            message: `Are you sure you want to delete "${name}"?`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        deleteVoice(id, {
            onSuccess: () => toast.success('Voice model deleted'),
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const handlePreview = async (voiceId) => {
        setPreviewLoading(true);
        try {
            const res = await previewVoice({ voiceId });
            setPreviewJobId(res?.job_id || null);
            toast.success('Preview job queued');
        } catch (e) {
            toast.error(`Preview failed: ${e.message}`);
        } finally {
            setPreviewLoading(false);
        }
    };

    const edit = (voice) => {
        setEditingId(voice.id);
        setFormData({
            name: voice.name,
            description: voice.description,
            type: voice.type,
            voice_profile: voice.voice_profile,
            language: voice.language,
            preview_text: voice.preview_text,
            model_path: voice.model_path,
            ...(voice.world_id ? { world_id: voice.world_id } : {}),
        });
        setShowCreate(true);
    };

    const handleDesign = async (e) => {
        e?.preventDefault();
        if (!designForm.name.trim() || !designForm.description.trim()) {
            toast.error('Voice name and natural language description are required');
            return;
        }
        try {
            const res = await designVoice({
                voices: [{
                    name: designForm.name.trim(),
                    description: designForm.description.trim(),
                    sample_text: designForm.sample_text.trim() || undefined,
                    language: designForm.language || 'en',
                }],
                sample_text: designForm.sample_text.trim() || undefined,
                language: designForm.language || 'en',
            });
            toast.success('Voice design job started! Generating reference voice...');
            if (res?.job_id) {
                setPreviewJobId(res.job_id);
            }
            setShowDesign(false);
            setDesignForm({ name: '', description: '', sample_text: '', language: 'en' });
        } catch (err) {
            toast.error(err?.message ? `Design failed: ${err.message}` : 'Failed to design voice');
        }
    };

    const closeForm = () => {
        setShowCreate(false);
        setEditingId(null);
        setFormData({});
    };

    if (isLoading) {
        return (
            <RoleplayPageShell title="Voice Models" description="Reusable voices for narration and text-to-speech." icon={Volume2}>
                <div className="py-12 text-center text-slate-400">Loading voices…</div>
            </RoleplayPageShell>
        );
    }

    // Before the error branch below this page fell through to
    // "No voice models yet — Create a voice model", next to a vault that
    // already had voices. See components/common/QueryState.jsx.
    if (isError) {
        return (
            <RoleplayPageShell title="Voice Models" description="Reusable voices for narration and text-to-speech." icon={Volume2}>
                <QueryErrorState noun="voices" error={error} onRetry={refetch} />
            </RoleplayPageShell>
        );
    }

    return (
        <RoleplayPageShell
            title="Voice Models"
            description="Reusable voices for narration and text-to-speech."
            icon={Volume2}
            actions={
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setShowDesign(true)}
                        className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 px-4 py-2 font-medium text-white transition hover:from-purple-500 hover:to-indigo-500 shadow-md text-sm"
                    >
                        <Wand2 size={16} /> Design with AI
                    </button>
                    <button
                        onClick={() => setShowCreate(true)}
                        className="flex items-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 font-medium text-slate-950 transition hover:bg-cyan-400 text-sm"
                    >
                        <Plus size={16} /> Create Voice
                    </button>
                </div>
            }
        >

            <AnimatePresence>
                {showCreate && (
                    <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        className="mb-6 bg-gray-900 border border-gray-700 rounded-xl p-6"
                    >
                        <h2 className="text-xl font-semibold text-white mb-4">
                            {editingId ? 'Edit Voice Model' : 'New Voice Model'}
                        </h2>
                        <FormInput
                            label="Name"
                            required
                            placeholder="Voice model name"
                            value={formData.name}
                            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                        />
                        <label htmlFor="voice-world-select" className="block text-xs text-gray-400 mb-1">World (Optional)</label>
                        <select
                            id="voice-world-select"
                            value={formData.world_id || ''}
                            onChange={(e) => setFormData({ ...formData, world_id: e.target.value })}
                            className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50 mb-3"
                        >
                            <option value="">No World (Global)</option>
                            {worlds.map(w => (
                                <option key={w.id} value={w.id}>{w.name}</option>
                            ))}
                        </select>
                        <label htmlFor="voice-type" className="block text-xs text-gray-400 mb-1">Type</label>
                        <select
                            id="voice-type"
                            value={formData.type || 'qwen3_tts'}
                            onChange={(e) => setFormData({ ...formData, type: e.target.value })}
                            className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50 mb-3"
                        >
                            {TYPE_OPTIONS.map(opt => (
                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                            ))}
                        </select>
                        <FormInput
                            label="Voice Profile"
                            placeholder="e.g. test_speaker, default"
                            value={formData.voice_profile}
                            onChange={(e) => setFormData({ ...formData, voice_profile: e.target.value })}
                        />
                        <FormInput
                            label="Language"
                            placeholder="e.g. en, es, fr"
                            value={formData.language}
                            onChange={(e) => setFormData({ ...formData, language: e.target.value })}
                        />
                        <FormInput
                            label="Preview Text"
                            placeholder="Sample text for preview"
                            value={formData.preview_text}
                            onChange={(e) => setFormData({ ...formData, preview_text: e.target.value })}
                        />
                        <FormInput
                            label="Model Path"
                            placeholder="Optional: path to the model file"
                            value={formData.model_path}
                            onChange={(e) => setFormData({ ...formData, model_path: e.target.value })}
                        />
                        {/* Preset selector - shown when type is qwen3_preset */}
                        {formData.type === 'qwen3_preset' && presets.length > 0 && (
                            <div>
                                <label htmlFor="voice-preset" className="block text-xs text-gray-400 mb-1">Preset Voice</label>
                                <select
                                    id="voice-preset"
                                    value={formData.voice_preset || ''}
                                    onChange={(e) => setFormData({ ...formData, voice_preset: e.target.value })}
                                    className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50 mb-3"
                                >
                                    <option value="">Select a preset voice...</option>
                                    {presets.map(preset => (
                                        <option key={preset.id} value={preset.id}>
                                            {preset.name} — {preset.description}
                                        </option>
                                    ))}
                                </select>
                                {formData.voice_preset && (
                                    <p className="text-xs text-purple-400 mt-1">
                                        Selected: {presets.find(p => p.id === formData.voice_preset)?.name}
                                    </p>
                                )}
                            </div>
                        )}
                        <FormInput
                            label="Description"
                            placeholder="Optional description"
                            value={formData.description}
                            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                        />
                        <div className="flex justify-end gap-3">
                            <button onClick={closeForm} className="px-4 py-2 text-gray-400 hover:text-white">
                                Cancel
                            </button>
                            <button
                                onClick={editingId ? handleUpdate : handleCreate}
                                className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg"
                            >
                                {editingId ? 'Update' : 'Create'}
                            </button>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            {voices.length === 0 ? (
                <EmptyState
                    icon={Volume2}
                    title="No voice models yet"
                    description="Create a voice model to enable text-to-speech narration for your characters."
                    primaryLabel="Create Voice"
                    onAction={() => setShowCreate(true)}
                />
            ) : (
                <div className="space-y-3">
                    {voices.map((voice) => (
                        <motion.div
                            key={voice.id}
                            className="bg-gray-900 border border-gray-700 rounded-xl p-4 flex items-center justify-between"
                        >
                            <div className="flex-1">
                                <div className="flex items-center gap-2">
                                    <h3 className="font-medium text-white">{voice.name}</h3>
                                    {voice.type && (
                                        <span className="text-xs px-2 py-0.5 bg-gray-700 rounded text-gray-300">
                                            {voice.type}
                                        </span>
                                    )}
                                </div>
                                {voice.voice_profile && (
                                    <p className="text-sm text-gray-400">Profile: {voice.voice_profile}</p>
                                )}
                                {voice.preview_text && (
                                    <p className="text-xs text-gray-500 mt-1 line-clamp-1">
                                        Preview: "{voice.preview_text}"
                                    </p>
                                )}
                                {voice.preview_path && (
                                    <audio
                                        src={assetUrl(voice.preview_path)}
                                        controls
                                        className="mt-2 h-8 rounded w-full max-w-xs"
                                    />
                                )}
                            </div>
                            <div className="flex items-center gap-2">
                                <button
                                    onClick={() => handlePreview(voice.id)}
                                    disabled={previewLoading}
                                    className="p-1.5 text-purple-400 hover:text-purple-300 disabled:opacity-50"
                                    title="Preview voice"
                                >
                                    <Play size={16} />
                                </button>
                                <button
                                    onClick={() => edit(voice)}
                                    className="p-1.5 text-blue-400 hover:text-blue-300"
                                    title="Edit"
                                >
                                    <Edit3 size={16} />
                                </button>
                                <button
                                    onClick={() => handleDelete(voice.id, voice.name)}
                                    className="p-1.5 text-red-400 hover:text-red-300"
                                    title="Delete"
                                >
                                    <Trash2 size={16} />
                                </button>
                            </div>
                        </motion.div>
                    ))}
                </div>
            )}

            {/* Design Voice with AI Modal */}
            {showDesign && (
                <ModalOverlay onClose={() => setShowDesign(false)} className="z-[60] bg-black/80 backdrop-blur-sm">
                    <div className="bg-gray-900 border border-purple-500/30 rounded-2xl p-6 w-full max-w-lg shadow-2xl space-y-4" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-between pb-3 border-b border-white/10">
                            <div className="flex items-center gap-2">
                                <Sparkles className="text-purple-400" size={20} />
                                <h3 className="text-lg font-bold text-white">Design Voice with AI</h3>
                            </div>
                            <button onClick={() => setShowDesign(false)} aria-label="Close design voice modal" className="text-gray-400 hover:text-white p-1 rounded-lg">
                                <X size={18} />
                            </button>
                        </div>
                        <p className="text-xs text-gray-300 leading-relaxed">
                            Describe the voice in natural language. The TTS engine will synthesize a unique vocal reference matching your description.
                        </p>
                        <form onSubmit={handleDesign} className="space-y-4">
                            <div>
                                <label htmlFor="design-voice-name" className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1">
                                    Voice Name *
                                </label>
                                <input
                                    id="design-voice-name"
                                    type="text"
                                    required
                                    placeholder="e.g. Morgana, Old Wizard, Silver-tongued Rogue"
                                    value={designForm.name}
                                    onChange={(e) => setDesignForm({ ...designForm, name: e.target.value })}
                                    className="w-full bg-gray-800 border border-white/10 rounded-xl px-3 py-2 text-sm text-white focus:outline-none focus:border-purple-500"
                                />
                            </div>
                            <div>
                                <label htmlFor="design-voice-description" className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1">
                                    Voice Description *
                                </label>
                                <textarea
                                    id="design-voice-description"
                                    required
                                    rows={3}
                                    placeholder="e.g. A deep, raspy, world-weary baritone with a Scottish accent, slow speaking cadence, and rich undertones."
                                    value={designForm.description}
                                    onChange={(e) => setDesignForm({ ...designForm, description: e.target.value })}
                                    className="w-full bg-gray-800 border border-white/10 rounded-xl px-3 py-2 text-sm text-white focus:outline-none focus:border-purple-500 resize-none"
                                />
                            </div>
                            <div>
                                <label htmlFor="design-voice-sample-text" className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1">
                                    Sample Passage (Optional)
                                </label>
                                <input
                                    id="design-voice-sample-text"
                                    type="text"
                                    placeholder='Default: "The tide is out, and the harbour bell has not rung since spring."'
                                    value={designForm.sample_text}
                                    onChange={(e) => setDesignForm({ ...designForm, sample_text: e.target.value })}
                                    className="w-full bg-gray-800 border border-white/10 rounded-xl px-3 py-2 text-sm text-white focus:outline-none focus:border-purple-500"
                                />
                            </div>
                            <div className="flex justify-end gap-3 pt-2">
                                <button
                                    type="button"
                                    onClick={() => setShowDesign(false)}
                                    className="px-4 py-2 rounded-xl text-xs font-semibold text-gray-400 hover:text-white transition-colors"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    disabled={isDesigning || !designForm.name.trim() || !designForm.description.trim()}
                                    className="px-5 py-2 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white rounded-xl text-xs font-bold flex items-center gap-2 disabled:opacity-50 transition-all shadow-md"
                                >
                                    {isDesigning ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}
                                    Synthesize Voice
                                </button>
                            </div>
                        </form>
                    </div>
                </ModalOverlay>
            )}
        </RoleplayPageShell>
    );
}
