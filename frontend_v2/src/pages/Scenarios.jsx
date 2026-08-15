import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Edit3, Trash2, Copy, Play, Save, X, Tag } from 'lucide-react';
import toast from 'react-hot-toast';
import {
    useScenarios,
    useCreateScenario,
    useUpdateScenario,
    useDeleteScenario,
    useApplyScenario,
} from '../hooks/useWorldVault';
import EmptyState from '../components/EmptyState';
import { useConfirmation } from '../store/confirmationStore';

const FORM_FIELDS = [
    { key: 'name', label: 'Name', type: 'text', required: true, placeholder: 'Scenario name' },
    { key: 'description', label: 'Description', type: 'textarea', placeholder: 'What is this scenario about?' },
    { key: 'prompt_template', label: 'Prompt Template', type: 'textarea', placeholder: 'The system prompt or starter prompt for this scenario...' },
    { key: 'default_checkpoint', label: 'Default Checkpoint', type: 'text', placeholder: 'e.g. anything-v5' },
    { key: 'default_voice_profile', label: 'Default Voice Profile', type: 'text', placeholder: 'e.g. en_speaker_01' },
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

export default function Scenarios() {
    const [editingId, setEditingId] = useState(null);
    const [showCreate, setShowCreate] = useState(false);
    const [formData, setFormData] = useState({});

    const { data: scenarios = [], isLoading } = useScenarios();
    const { mutate: createScenario } = useCreateScenario();
    const { mutate: updateScenario } = useUpdateScenario();
    const { mutate: deleteScenario } = useDeleteScenario();
    const { mutate: applyScenario } = useApplyScenario();
    const { confirm } = useConfirmation();

    const handleCreate = () => {
        if (!formData.name) {
            toast.error('Name is required');
            return;
        }
        createScenario(formData, {
            onSuccess: () => {
                toast.success('Scenario created');
                setShowCreate(false);
                setFormData({});
            },
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const handleUpdate = () => {
        updateScenario({ id: editingId, ...formData }, {
            onSuccess: () => {
                toast.success('Scenario updated');
                setEditingId(null);
                setFormData({});
            },
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const handleDelete = async (id, name) => {
        const ok = await confirm(`Delete "${name}"?`, 'This cannot be undone.');
        if (!ok) return;
        deleteScenario(id, {
            onSuccess: () => toast.success('Scenario deleted'),
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const handleApply = async (scenario) => {
        const targetType = prompt('Apply to (chat/story):', 'chat') || 'chat';
        const targetId = prompt('Target ID:', '');
        if (!targetId) return toast.error('Target ID is required');
        applyScenario({ scenarioId: scenario.id, target_type: targetType, target_id: targetId }, {
            onSuccess: () => toast.success(`Applied to ${targetType}`),
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const edit = (scenario) => {
        setEditingId(scenario.id);
        setFormData({
            name: scenario.name,
            description: scenario.description,
            prompt_template: scenario.prompt_template,
            default_checkpoint: scenario.default_checkpoint,
            default_voice_profile: scenario.default_voice_profile,
        });
        setShowCreate(true);
    };

    const closeForm = () => {
        setShowCreate(false);
        setEditingId(null);
        setFormData({});
    };


    return (
        <div className="p-6 max-w-4xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <h1 className="text-2xl font-bold text-white">Scenarios</h1>
                <button
                    onClick={() => setShowCreate(true)}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg flex items-center gap-2 transition-colors"
                >
                    <Plus size={18} />
                    Create Scenario
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
                            {editingId ? 'Edit Scenario' : 'New Scenario'}
                        </h2>
                        {FORM_FIELDS.map((field) => (
                            <FormInput
                                key={field.key}
                                label={field.label}
                                type={field.type}
                                placeholder={field.placeholder}
                                required={field.required}
                                value={formData[field.key]}
                                onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
                            />
                        ))}
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

            {isLoading ? (
                <div className="space-y-3">
                    {[1, 2, 3].map(i => (
                        <div key={i} className="bg-gray-900 border border-gray-700 rounded-xl p-4 flex items-center justify-between animate-pulse">
                            <div className="flex-1 space-y-2">
                                <div className="h-5 bg-gray-700 rounded w-1/4"></div>
                                <div className="h-4 bg-gray-700 rounded w-2/3"></div>
                                <div className="h-3 bg-gray-700 rounded w-1/2"></div>
                            </div>
                            <div className="flex gap-2">
                                <div className="w-8 h-8 rounded bg-gray-700"></div>
                                <div className="w-8 h-8 rounded bg-gray-700"></div>
                            </div>
                        </div>
                    ))}
                </div>
            ) : scenarios.length === 0 ? (
                <EmptyState
                    icon={Tag}
                    title="No scenarios yet"
                    description="Create a scenario to define reusable prompt templates for chats and stories."
                    actionLabel="Create Scenario"
                    onAction={() => setShowCreate(true)}
                />
            ) : (
                <div className="space-y-3">
                    {scenarios.map((scenario) => (
                        <motion.div
                            key={scenario.id}
                            className="bg-gray-900 border border-gray-700 rounded-xl p-4 flex items-center justify-between"
                        >
                            <div className="flex-1">
                                <h3 className="font-medium text-white">{scenario.name}</h3>
                                {scenario.description && (
                                    <p className="text-sm text-gray-400 mt-1">{scenario.description}</p>
                                )}
                                {scenario.prompt_template && (
                                    <p className="text-xs text-gray-500 mt-1 line-clamp-1">{scenario.prompt_template}</p>
                                )}
                            </div>
                            <div className="flex items-center gap-2">
                                <button
                                    onClick={() => handleApply(scenario)}
                                    className="p-1.5 text-purple-400 hover:text-purple-300"
                                    title="Apply to chat or story"
                                >
                                    <Play size={16} />
                                </button>
                                <button
                                    onClick={() => edit(scenario)}
                                    className="p-1.5 text-blue-400 hover:text-blue-300"
                                    title="Edit"
                                >
                                    <Edit3 size={16} />
                                </button>
                                <button
                                    onClick={() => handleDelete(scenario.id, scenario.name)}
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
