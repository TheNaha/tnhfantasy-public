import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Edit3, Trash2, Play, Save, X, Tag, MessageSquare, BookOpen, Sparkles } from 'lucide-react';
import toast from 'react-hot-toast';
import {
    useScenarios,
    useCreateScenario,
    useUpdateScenario,
    useDeleteScenario,
    useApplyScenario,
} from '../hooks/useWorldVault';
import { useChats } from '../hooks/useChats';
import { useStories } from '../hooks/useStories';
import { useModelDirectories } from '../hooks/useModelDirectories';
import EmptyState from '../components/EmptyState';
import FormInput from '../components/common/FormInput';
import { useConfirmation } from '../store/confirmationStore';
import RoleplayPageShell from '../components/RoleplayPageShell';
import { useEscapeKey } from '../hooks/useEscapeKey';

const FORM_FIELDS = [
    { key: 'name', label: 'Name', type: 'text', required: true, placeholder: 'Scenario name' },
    { key: 'description', label: 'Description', type: 'textarea', placeholder: 'What is this scenario about?' },
    { key: 'prompt_template', label: 'Prompt Template', type: 'textarea', placeholder: 'The system prompt or starter prompt for this scenario...' },
    { key: 'default_checkpoint', label: 'Default Checkpoint', type: 'text', placeholder: 'e.g. anything-v5' },
    { key: 'default_voice_profile', label: 'Default Voice Profile', type: 'text', placeholder: 'e.g. en_speaker_01' },
];

export default function Scenarios() {
    const [editingId, setEditingId] = useState(null);
    const [showCreate, setShowCreate] = useState(false);
    const [formData, setFormData] = useState({});
    const [applyingScenario, setApplyingScenario] = useState(null);
    const [applyTargetType, setApplyTargetType] = useState('chat');

    const { data: scenarios = [], isLoading } = useScenarios();
    const { mutate: createScenario } = useCreateScenario();
    const { mutate: updateScenario } = useUpdateScenario();
    const { mutate: deleteScenario } = useDeleteScenario();
    const { mutate: applyScenario } = useApplyScenario();
    const { data: chats = [] } = useChats();
    const { data: stories = [] } = useStories();
    const { modelsByKey } = useModelDirectories([{ key: 'checkpoints', directory: 'models/checkpoints', label: 'checkpoints' }]);
    const checkpoints = modelsByKey.checkpoints || [];
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
        const ok = await confirm({
            title: 'Delete Scenario',
            message: `Are you sure you want to delete "${name}"?`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        deleteScenario(id, {
            onSuccess: () => toast.success('Scenario deleted'),
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const handleApply = (scenario) => {
        setApplyingScenario(scenario);
        setApplyTargetType('chat');
    };

    const submitApply = (targetId) => {
        if (!targetId) return toast.error('Select a target first');
        const scenario = applyingScenario;
        setApplyingScenario(null);
        applyScenario({ scenarioId: scenario.id, targetType: applyTargetType, targetId }, {
            onSuccess: () => toast.success(`Applied to ${applyTargetType}`),
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const applyTargets = applyTargetType === 'chat' ? chats : stories;

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
        <RoleplayPageShell
            title="Scenarios"
            description="Reusable starting situations for chats and stories."
            icon={Sparkles}
            actions={
                <button
                    onClick={() => setShowCreate(true)}
                    className="flex items-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 font-medium text-slate-950 transition hover:bg-cyan-400"
                >
                    <Plus size={18} /> Create Scenario
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
                            {editingId ? 'Edit Scenario' : 'New Scenario'}
                        </h2>
                        {FORM_FIELDS.map((field) => (
                            field.key === 'default_checkpoint' ? (
                                <div key={field.key}>
                                    <label className="block text-xs text-gray-400 mb-1">{field.label}</label>
                                    <select
                                        value={formData[field.key] || ''}
                                        onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
                                        className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50 mb-3"
                                    >
                                        <option value="">Auto (global default)</option>
                                        {checkpoints.map(c => (
                                            <option key={c.name} value={c.name}>{c.display_name || c.name}</option>
                                        ))}
                                    </select>
                                </div>
                            ) : (
                                <FormInput
                                    key={field.key}
                                    label={field.label}
                                    type={field.type}
                                    placeholder={field.placeholder}
                                    required={field.required}
                                    value={formData[field.key]}
                                    onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
                                />
                            )
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
                    primaryLabel="Create Scenario"
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

            <AnimatePresence>
                {applyingScenario && (
                    <ApplyScenarioModal
                        scenario={applyingScenario}
                        targetType={applyTargetType}
                        setTargetType={setApplyTargetType}
                        targets={applyTargets}
                        onApply={submitApply}
                        onClose={() => setApplyingScenario(null)}
                    />
                )}
            </AnimatePresence>
        </RoleplayPageShell>
    );
}

function ApplyScenarioModal({ scenario, targetType, setTargetType, targets, onApply, onClose }) {
    // Escape dismisses, matching the shared ModalOverlay dialogs and the
    // "Esc → Close modals" line in KeyboardShortcutsModal.
    useEscapeKey(onClose, true);
    const [selectedId, setSelectedId] = useState('');
    const label = targetType === 'chat' ? 'chat' : 'story';

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
                className="bg-gray-900 border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl max-h-[85vh] overflow-y-auto"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">Apply &ldquo;{scenario.name}&rdquo;</h2>
                    <button onClick={onClose} className="text-gray-400 hover:text-white"><X size={20} /></button>
                </div>

                <div className="flex gap-2 mb-4">
                    <button
                        type="button"
                        onClick={() => { setTargetType('chat'); setSelectedId(''); }}
                        className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm transition-colors ${targetType === 'chat' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}
                    >
                        <MessageSquare size={14} /> Chat
                    </button>
                    <button
                        type="button"
                        data-testid="target-type-story"
                        onClick={() => { setTargetType('story'); setSelectedId(''); }}
                        className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm transition-colors ${targetType === 'story' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}
                    >
                        <BookOpen size={14} /> Story
                    </button>
                </div>

                <label className="block text-sm font-medium text-gray-300 mb-1">Select {label}</label>
                {targets.length === 0 ? (
                    <p className="text-xs text-gray-600 border border-gray-700/50 rounded-lg px-3 py-2">
                        No {label}s available — create one first.
                    </p>
                ) : (
                    <div className="max-h-48 overflow-y-auto border border-gray-600 rounded-lg bg-gray-800/60 divide-y divide-white/5">
                        {targets.map((t) => {
                            const active = selectedId === t.id;
                            return (
                                <button
                                    key={t.id}
                                    type="button"
                                    onClick={() => setSelectedId(t.id)}
                                    className={'w-full text-left px-3 py-2 text-xs transition-colors ' + (active ? 'bg-indigo-500/20 text-indigo-300' : 'text-gray-400 hover:bg-white/5')}
                                >
                                    {t.name || t.title || t.id.slice(0, 8)}
                                </button>
                            );
                        })}
                    </div>
                )}

                <div className="flex gap-2 justify-end mt-4">
                    <button onClick={onClose} className="px-4 py-2 text-gray-400 hover:text-white transition-colors">Cancel</button>
                    <button
                        onClick={() => onApply(selectedId)}
                        disabled={!selectedId}
                        className="px-4 py-2 bg-purple-600 text-white rounded-lg font-medium hover:bg-purple-700 disabled:opacity-50 transition-colors"
                    >
                        Apply
                    </button>
                </div>
            </motion.div>
        </motion.div>
    );
}
