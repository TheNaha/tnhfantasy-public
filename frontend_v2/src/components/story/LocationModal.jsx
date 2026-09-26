import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Save, Tag } from 'lucide-react';
import toast from 'react-hot-toast';
import { useQueryClient } from '@tanstack/react-query';
import { useCreateLocation, useUpdateLocation } from '../../hooks/useLocations';
import { useEscapeKey } from '../../hooks/useEscapeKey';

export function LocationModal({ isOpen, onClose, location }) {
    // Escape dismisses, matching every other dialog expectation.
    useEscapeKey(onClose, !!isOpen);

    const [form, setForm] = useState({ name: '', description: '', atmosphere: '', tags: [] });
    const [saving, setSaving] = useState(false);
    const queryClient = useQueryClient();
    const createLocation = useCreateLocation();
    const updateLocation = useUpdateLocation();

    useEffect(() => {
        if (isOpen) {
            setForm({
                name: location?.name || '',
                description: location?.description || '',
                atmosphere: location?.atmosphere || '',
                tags: location?.tags || [],
            });
        }
    }, [isOpen, location]);

    if (!isOpen) return null;

    const handleSave = async () => {
        if (!form.name.trim()) {
            toast.error('Name is required');
            return;
        }
        setSaving(true);
        try {
            if (location) {
                await updateLocation.mutateAsync({ id: location.id, ...form });
                toast.success('Location updated');
            } else {
                await createLocation.mutateAsync(form);
                toast.success('Location created');
            }
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'locations'] });
            onClose();
        } catch (e) {
            console.error(e);
            toast.error('Failed to save location');
        } finally {
            setSaving(false);
        }
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
                    {/* Header */}
                    <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 bg-gray-900/50">
                        <h2 className="text-xl font-semibold text-gray-100">
                            {location ? 'Edit Location' : 'Create Location'}
                        </h2>
                        <button onClick={onClose} className="p-2 text-gray-400 hover:text-white rounded-lg hover:bg-white/10 transition-colors">
                            <X size={20} />
                        </button>
                    </div>

                    {/* Content */}
                    <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
                        <div className="space-y-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-1.5">Name</label>
                                <input
                                    type="text"
                                    value={form.name}
                                    onChange={(e) => setForm(prev => ({ ...prev, name: e.target.value }))}
                                    className="w-full bg-black/40 border border-gray-700 rounded-lg px-4 py-2.5 text-gray-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all"
                                    placeholder="Location Name"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-1.5">Description</label>
                                <textarea
                                    value={form.description}
                                    onChange={(e) => setForm(prev => ({ ...prev, description: e.target.value }))}
                                    className="w-full h-32 bg-black/40 border border-gray-700 rounded-lg px-4 py-3 text-gray-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all resize-none custom-scrollbar"
                                    placeholder="A description of this location..."
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-1.5">Atmosphere</label>
                                <textarea
                                    value={form.atmosphere}
                                    onChange={(e) => setForm(prev => ({ ...prev, atmosphere: e.target.value }))}
                                    className="w-full h-24 bg-black/40 border border-gray-700 rounded-lg px-4 py-3 text-gray-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all resize-none custom-scrollbar"
                                    placeholder="e.g. Misty, foreboding, bustling market square..."
                                />
                                <p className="text-xs text-gray-500 mt-1">Sensory details and mood of the location.</p>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-1.5 flex items-center gap-1.5">
                                    <Tag size={14} className="text-purple-400" /> Tags
                                </label>
                                <input
                                    type="text"
                                    value={form.tags.join(', ')}
                                    onChange={(e) => setForm(prev => ({ ...prev, tags: e.target.value.split(',').map(t => t.trim()).filter(Boolean) }))}
                                    className="w-full bg-black/40 border border-gray-700 rounded-lg px-4 py-2.5 text-gray-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all"
                                    placeholder="e.g. city, tavern, dungeon (comma-separated)"
                                />
                                <p className="text-xs text-gray-500 mt-1">Tags help with semantic lorebook lookups.</p>
                            </div>
                        </div>
                    </div>

                    {/* Footer */}
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
                            {saving ? 'Saving...' : location ? 'Save Changes' : 'Create Location'}
                        </button>
                    </div>
                </motion.div>
            </div>
        </AnimatePresence>
    );
}
