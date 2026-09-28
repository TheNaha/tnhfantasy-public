import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Edit3, Trash2, Play, Volume2, FileText, AlertCircle } from 'lucide-react';
import toast from 'react-hot-toast';
import { useQueryClient } from '@tanstack/react-query';
import {
    useVoices,
    useCreateVoice,
    useUpdateVoice,
    useDeleteVoice,
    useVoicePreview,
} from '../hooks/useWorldVault';
import { useJobStatus } from '../hooks/useJobStatus';
import { assetUrl } from '../utils/assetUrl';
import EmptyState from '../components/EmptyState';
import FormInput from '../components/common/FormInput';
import { useConfirmation } from '../store/confirmationStore';
import RoleplayPageShell from '../components/RoleplayPageShell';

const TYPE_OPTIONS = [
    { value: 'xtts', label: 'XTTS v2' },
    { value: 'bark', label: 'Bark' },
    { value: 'coqui', label: 'Coqui' },
    { value: 'embedding', label: 'Embedding' },
    { value: 'other', label: 'Other' },
];

export default function Voices() {
    const [editingId, setEditingId] = useState(null);
    const [showCreate, setShowCreate] = useState(false);
    const [formData, setFormData] = useState({});
    const [previewLoading, setPreviewLoading] = useState(false);
    const [previewJobId, setPreviewJobId] = useState(null);
    const queryClient = useQueryClient();

    const { data: voices = [], isLoading } = useVoices();
    const { mutate: createVoice } = useCreateVoice();
    const { mutate: updateVoice } = useUpdateVoice();
    const { mutate: deleteVoice } = useDeleteVoice();
    const { mutateAsync: previewVoice } = useVoicePreview();
    const { confirm } = useConfirmation();

    const { data: previewJob } = useJobStatus(previewJobId, { enabled: !!previewJobId });

    useEffect(() => {
        if (!previewJob) return;
        if (previewJob.status === 'completed') {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'voices'] });
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
        createVoice(formData, {
            onSuccess: () => {
                toast.success('Voice model created');
                setShowCreate(false);
                setFormData({});
            },
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const handleUpdate = () => {
        updateVoice({ id: editingId, ...formData }, {
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
        });
        setShowCreate(true);
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

    return (
        <RoleplayPageShell
            title="Voice Models"
            description="Reusable voices for narration and text-to-speech."
            icon={Volume2}
            actions={
                <button
                    onClick={() => setShowCreate(true)}
                    className="flex items-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 font-medium text-slate-950 transition hover:bg-cyan-400"
                >
                    <Plus size={18} /> Create Voice
                </button>
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
                        <label className="block text-xs text-gray-400 mb-1">Type</label>
                        <select
                            value={formData.type || 'xtts'}
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
        </RoleplayPageShell>
    );
}
