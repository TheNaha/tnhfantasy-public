import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Edit3, Trash2, Play, Volume2, FileText, AlertCircle } from 'lucide-react';
import toast from 'react-hot-toast';
import {
    useVoices,
    useCreateVoice,
    useUpdateVoice,
    useDeleteVoice,
    useVoicePreview,
} from '../hooks/useWorldVault';
import EmptyState from '../components/EmptyState';
import { useConfirmation } from '../store/confirmationStore';

const TYPE_OPTIONS = [
    { value: 'xtts', label: 'XTTS v2' },
    { value: 'bark', label: 'Bark' },
    { value: 'coqui', label: 'Coqui' },
    { value: 'other', label: 'Other' },
];

const FormInput = ({ label, value, onChange, type = 'text', placeholder, required }) => (
    <div className="mb-4">
        <label className="block text-sm font-medium text-gray-300 mb-1">{label}{required && '*'}</label>
        {type === 'textarea' ? (
            <textarea
                className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                value={value || ''}
                onChange={onChange}
                placeholder={placeholder}
                rows={3}
            />
        ) : (
            <input
                type={type}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={value || ''}
                onChange={onChange}
                placeholder={placeholder}
            />
        )}
    </div>
);

export default function Voices() {
    const [editingId, setEditingId] = useState(null);
    const [showCreate, setShowCreate] = useState(false);
    const [formData, setFormData] = useState({});
    const [previewLoading, setPreviewLoading] = useState(false);

    const { data: voices = [], isLoading } = useVoices();
    const { mutate: createVoice } = useCreateVoice();
    const { mutate: updateVoice } = useUpdateVoice();
    const { mutate: deleteVoice } = useDeleteVoice();
    const { mutate: previewVoice } = useVoicePreview();
    const { confirm } = useConfirmation();

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
        const ok = await confirm(`Delete "${name}"?`, 'This cannot be undone.');
        if (!ok) return;
        deleteVoice(id, {
            onSuccess: () => toast.success('Voice model deleted'),
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const handlePreview = (voiceId) => {
        setPreviewLoading(true);
        previewVoice(voiceId, {
            onSuccess: () => {
                toast.success('Preview job queued');
                setPreviewLoading(false);
            },
            onError: (e) => {
                toast.error(`Preview failed: ${e.message}`);
                setPreviewLoading(false);
            },
        });
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
        return <div className="p-6">Loading voices...</div>;
    }

    return (
        <div className="p-6 max-w-4xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <h1 className="text-2xl font-bold text-white">Voice Models</h1>
                <button
                    onClick={() => setShowCreate(true)}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg flex items-center gap-2 transition-colors"
                >
                    <Plus size={18} />
                    Create Voice
                </button>
            </div>

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
                        <FormInput
                            label="Type"
                            placeholder="Select type"
                            value={formData.type}
                            onChange={(e) => setFormData({ ...formData, type: e.target.value })}
                        />
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
                    actionLabel="Create Voice"
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
        </div>
    );
}
