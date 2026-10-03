import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Edit3, Trash2, Save, UserRound } from 'lucide-react';
import toast from 'react-hot-toast';
import {
    usePersonas,
    useCreatePersona,
    useUpdatePersona,
    useDeletePersona,
} from '../hooks/useWorldVault';
import EmptyState from '../components/EmptyState';
import FormInput from '../components/common/FormInput';
import { useConfirmation } from '../store/confirmationStore';
import RoleplayPageShell from '../components/RoleplayPageShell';
import { QueryErrorState } from '../components/common/QueryState';

export default function Personas() {
    const [editingId, setEditingId] = useState(null);
    const [showCreate, setShowCreate] = useState(false);
    const [formData, setFormData] = useState({});

    // See components/common/QueryState.jsx — a failed fetch used to render
    // "No personas yet" next to a vault that already had one.
    const { data: personas = [], isLoading, isError, error, refetch } = usePersonas();
    const { mutate: createPersona } = useCreatePersona();
    const { mutate: updatePersona } = useUpdatePersona();
    const { mutate: deletePersona } = useDeletePersona();
    const { confirm } = useConfirmation();

    const handleCreate = () => {
        if (!formData.name?.trim()) {
            toast.error('Name is required');
            return;
        }
        createPersona(formData, {
            onSuccess: () => {
                toast.success('Persona created');
                closeForm();
            },
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const handleUpdate = () => {
        updatePersona({ id: editingId, ...formData }, {
            onSuccess: () => {
                toast.success('Persona updated');
                closeForm();
            },
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const handleDelete = async (id, name) => {
        const ok = await confirm({
            title: 'Delete Persona',
            message: `Delete "${name}"? Chats using it keep their custom persona fields but lose the link.`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        deletePersona(id, {
            onSuccess: () => toast.success('Persona deleted'),
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const edit = (persona) => {
        setEditingId(persona.id);
        setFormData({ name: persona.name, description: persona.description });
        setShowCreate(true);
    };

    const closeForm = () => {
        setShowCreate(false);
        setEditingId(null);
        setFormData({});
    };

    return (
        <RoleplayPageShell
            title="Personas"
            description="Who you are in a conversation. A persona sets {{user}} in the system prompt."
            icon={UserRound}
            actions={
                <button
                    onClick={() => setShowCreate(true)}
                    className="flex items-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 font-medium text-slate-950 transition hover:bg-cyan-400"
                >
                    <Plus size={18} /> Create Persona
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
                            {editingId ? 'Edit Persona' : 'New Persona'}
                        </h2>
                        <FormInput
                            label="Name"
                            type="text"
                            placeholder="Who are you in the story?"
                            required
                            value={formData.name}
                            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                        />
                        <FormInput
                            label="Description"
                            type="textarea"
                            placeholder="Appearance, personality, background — injected as [About you] into chats."
                            value={formData.description}
                            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                        />
                        <div className="flex justify-end gap-3">
                            <button onClick={closeForm} className="px-4 py-2 text-gray-400 hover:text-white">
                                Cancel
                            </button>
                            <button
                                data-testid="persona-save-btn"
                                onClick={editingId ? handleUpdate : handleCreate}
                                className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg flex items-center gap-2"
                            >
                                <Save size={16} />
                                {editingId ? 'Update' : 'Create'}
                            </button>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            {isLoading ? (
                <div className="space-y-3">
                    {[1, 2, 3].map(i => (
                        <div key={i} className="bg-gray-900 border border-gray-700 rounded-xl p-4 animate-pulse">
                            <div className="h-5 bg-gray-700 rounded w-1/4 mb-2"></div>
                            <div className="h-4 bg-gray-700 rounded w-2/3"></div>
                        </div>
                    ))}
                </div>
            ) : isError ? (
                <QueryErrorState noun="personas" error={error} onRetry={refetch} />
            ) : personas.length === 0 ? (
                <EmptyState
                    icon={UserRound}
                    title="No personas yet"
                    description="Create reusable user personas to be yourself in any conversation, with any character."
                    primaryLabel="Create Persona"
                    onAction={() => setShowCreate(true)}
                />
            ) : (
                <div className="space-y-3">
                    {personas.map((persona) => (
                        <motion.div
                            key={persona.id}
                            data-testid="persona-row"
                            className="bg-gray-900 border border-gray-700 rounded-xl p-4 flex items-center justify-between"
                        >
                            <div className="flex-1">
                                <h3 className="font-medium text-white">{persona.name}</h3>
                                {persona.description && (
                                    <p className="text-sm text-gray-400 mt-1 whitespace-pre-wrap line-clamp-3">{persona.description}</p>
                                )}
                            </div>
                            <div className="flex items-center gap-2">
                                <button
                                    onClick={() => edit(persona)}
                                    className="p-1.5 text-blue-400 hover:text-blue-300"
                                    title={`Edit ${persona.name}`}
                                >
                                    <Edit3 size={16} />
                                </button>
                                <button
                                    onClick={() => handleDelete(persona.id, persona.name)}
                                    className="p-1.5 text-red-400 hover:text-red-300"
                                    title={`Delete ${persona.name}`}
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
