import React, { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Save } from 'lucide-react';
import toast from 'react-hot-toast';
import { useQueryClient } from '@tanstack/react-query';

const fieldStyles = {
    input: "w-full bg-black/40 border border-gray-700 rounded-lg px-4 py-2.5 text-gray-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all",
    textarea: "w-full bg-black/40 border border-gray-700 rounded-lg px-4 py-3 text-gray-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all resize-none custom-scrollbar",
};

export function EntityModal({
    isOpen,
    onClose,
    entity,
    fields,
    createMutation,
    updateMutation,
    queryKey,
    title,
    successMessage = 'Saved',
    errorMessage = 'Failed to save',
}) {
    const initialForm = useMemo(
        () =>
            fields.reduce((acc, field) => {
                acc[field.name] = entity?.[field.name] ?? field.defaultValue ?? '';
                return acc;
            }, {}),
        [fields, entity]
    );
    const [form, setForm] = useState(initialForm);
    const [saving, setSaving] = useState(false);
    const queryClient = useQueryClient();

    useEffect(() => {
        if (isOpen) {
            setForm(initialForm);
        }
    }, [isOpen, initialForm]);

    if (!isOpen) return null;

    const handleSave = async () => {
        setSaving(true);
        try {
            if (entity) {
                await updateMutation.mutateAsync({ id: entity.id, ...form });
                toast.success(successMessage);
            } else {
                await createMutation.mutateAsync(form);
                toast.success(successMessage);
            }
            queryClient.invalidateQueries({ queryKey });
            onClose();
        } catch (e) {
            console.error(e);
            toast.error(errorMessage);
        } finally {
            setSaving(false);
        }
    };

    const renderField = (field) => {
        const value = form[field.name] || '';
        const handleChange = (e) => {
            const newValue = e.target.value;
            setForm(prev => ({ ...prev, [field.name]: newValue }));
        };

        if (field.type === 'textarea') {
            return (
                <div key={field.name}>
                    <label className="block text-sm font-medium text-gray-400 mb-1.5">{field.label}</label>
                    <textarea
                        value={value}
                        onChange={handleChange}
                        className={fieldStyles.textarea}
                        style={{ height: field.height || '128px' }}
                        placeholder={field.placeholder}
                    />
                    {field.hint && <p className="text-[10px] text-gray-500 mt-1">{field.hint}</p>}
                </div>
            );
        }

        if (field.type === 'tags') {
            return (
                <div key={field.name}>
                    <label className="block text-sm font-medium text-gray-400 mb-1.5 flex items-center gap-1.5">
                        {field.icon && <field.icon size={14} className={field.iconColor || 'text-purple-400'} />}
                        {field.label}
                    </label>
                    <input
                        type="text"
                        value={Array.isArray(value) ? value.join(', ') : value}
                        onChange={(e) => setForm(prev => ({ ...prev, [field.name]: e.target.value.split(',').map(t => t.trim()).filter(Boolean) }))}
                        className={fieldStyles.input}
                        placeholder={field.placeholder}
                    />
                </div>
            );
        }

        return (
            <div key={field.name}>
                <label className="block text-sm font-medium text-gray-400 mb-1.5">{field.label}</label>
                <input
                    type="text"
                    value={value}
                    onChange={handleChange}
                    className={fieldStyles.input}
                    placeholder={field.placeholder}
                />
            </div>
        );
    };

    return (
        <AnimatePresence>
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                    onClick={onClose}
                />
                <motion.div
                    initial={{ opacity: 0, scale: 0.95, y: 20 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95, y: 20 }}
                    className="relative w-full max-w-2xl bg-gray-900 border border-gray-700 rounded-xl shadow-2xl flex flex-col max-h-full overflow-hidden"
                >
                    <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 bg-gray-900/50">
                        <h2 className="text-xl font-semibold text-gray-100">{title}</h2>
                        <button onClick={onClose} className="p-2 text-gray-400 hover:text-white rounded-lg hover:bg-white/10 transition-colors">
                            <X size={20} />
                        </button>
                    </div>

                    <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
                        <div className="space-y-4">
                            {fields.map(renderField)}
                        </div>
                    </div>

                    <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-800 bg-gray-900/50">
                        <button
                            onClick={onClose}
                            className="px-4 py-2 text-sm font-medium text-gray-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handleSave}
                            disabled={saving}
                            className="flex items-center gap-2 px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors shadow-lg shadow-indigo-500/20"
                        >
                            <Save size={16} />
                            {saving ? 'Saving...' : entity ? 'Save Changes' : `Create ${title.replace('Create ', '')}`}
                        </button>
                    </div>
                </motion.div>
            </div>
        </AnimatePresence>
    );
}
