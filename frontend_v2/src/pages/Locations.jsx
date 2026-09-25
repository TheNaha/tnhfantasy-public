import React, { useState, useMemo, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Edit3, Trash2, Search, MapPin, X, Upload, Image as ImageIcon, Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { api } from '../api';
import { assetUrl } from '../utils/assetUrl';
import {
    useLocations,
    useCreateLocation,
    useUpdateLocation,
    useDeleteLocation,
    useSearchLocations,
} from '../hooks/useLocations';
import EmptyState from '../components/EmptyState';
import FormInput from '../components/common/FormInput';
import { useConfirmation } from '../store/confirmationStore';

const FORM_FIELDS = [
    { key: 'name', label: 'Name', type: 'text', required: true, placeholder: 'Location name' },
    { key: 'description', label: 'Description', type: 'textarea', placeholder: 'A vivid description of this location...' },
    { key: 'atmosphere', label: 'Atmosphere', type: 'textarea', placeholder: 'The mood, lighting, sounds, and feeling of this place...' },
    { key: 'tags', label: 'Tags', type: 'text', placeholder: 'tavern, forest, castle (comma-separated)' },
];

const DEFAULT_FORM = {
    name: '',
    description: '',
    atmosphere: '',
    tags: [],
    image_path: '',
};

import { useSearchParams } from 'react-router-dom';

export default function Locations() {
    const [searchParams, setSearchParams] = useSearchParams();
    const searchQuery = searchParams.get('q') || '';
    const imageInputRef = useRef(null);
    const [uploadingImage, setUploadingImage] = useState(false);

    const setSearchQuery = (query) => {
        if (query) {
            setSearchParams({ q: query }, { replace: true });
        } else {
            searchParams.delete('q');
            setSearchParams(searchParams, { replace: true });
        }
    };

    const [showForm, setShowForm] = useState(false);
    const [editingLocation, setEditingLocation] = useState(null);
    const [form, setForm] = useState(DEFAULT_FORM);
    const [tagInput, setTagInput] = useState('');

    const queryClient = useQueryClient();
    const { data: locations = [], isLoading } = useLocations();
    const createMutation = useCreateLocation();
    const updateMutation = useUpdateLocation();
    const deleteMutation = useDeleteLocation();
    const { confirm } = useConfirmation();

    // Server-side search when query is >= 2 chars; fall back to full list otherwise
    const isSearching = searchQuery.trim().length >= 2;
    const { data: searchResults, isFetching: isSearchFetching } = useSearchLocations(
        isSearching ? searchQuery.trim() : null
    );

    const filteredLocations = useMemo(() => {
        if (isSearching) return searchResults ?? [];
        return locations;
    }, [isSearching, searchResults, locations]);

    const resetForm = () => {
        setForm(DEFAULT_FORM);
        setTagInput('');
        setEditingLocation(null);
        setShowForm(false);
    };

    const handleSave = async () => {
        if (!form.name.trim()) {
            toast.error('Name is required');
            return;
        }
        try {
            const payload = {
                ...form,
                name: form.name.trim(),
                tags: form.tags || [],
            };
            if (editingLocation) {
                await updateMutation.mutateAsync({ id: editingLocation.id, ...payload });
                toast.success('Location updated');
            } else {
                await createMutation.mutateAsync(payload);
                toast.success('Location created');
            }
            resetForm();
        } catch {
            toast.error('Failed to save location');
        }
    };

    const handleEdit = (location) => {
        setEditingLocation(location);
        setForm({
            name: location.name || '',
            description: location.description || '',
            atmosphere: location.atmosphere || '',
            tags: location.tags || [],
            image_path: location.image_path || '',
        });
        setShowForm(true);
    };

    const handleDelete = async (location) => {
        const ok = await confirm({
            title: 'Delete Location',
            message: `Are you sure you want to delete "${location.name}"?`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            await deleteMutation.mutateAsync(location.id);
            toast.success('Location deleted');
        } catch {
            toast.error('Failed to delete location');
        }
    };

    const handleImageUpload = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file || !editingLocation) return;
        setUploadingImage(true);
        try {
            const formData = new FormData();
            formData.append('file', file);
            await api.post(`/api/v2/locations/${editingLocation.id}/image`, formData);
            await queryClient.invalidateQueries({ queryKey: ['world_vault', 'locations'] });
            toast.success('Image uploaded');
        } catch {
            toast.error('Failed to upload image');
        } finally {
            setUploadingImage(false);
        }
    };

    const addTag = () => {
        const tag = tagInput.trim();
        if (tag && !form.tags.includes(tag)) {
            setForm(f => ({ ...f, tags: [...(f.tags || []), tag] }));
        }
        setTagInput('');
    };

    const removeTag = (tag) => {
        setForm(f => ({ ...f, tags: (f.tags || []).filter(t => t !== tag) }));
    };

    return (
        <div className="p-6 max-w-5xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold text-white mb-1">Locations</h1>
                    <p className="text-gray-400 text-sm">World-building locations for your fantasy universe</p>
                </div>
                <button
                    onClick={() => { resetForm(); setShowForm(true); }}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors"
                >
                    <Plus size={16} /> New Location
                </button>
            </div>

            <div className="mb-6">
                <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search locations..."
                        className="w-full pl-10 pr-4 py-2.5 bg-gray-800 border border-white/10 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                    />
                </div>
            </div>

            {isLoading || (isSearching && isSearchFetching && !searchResults) ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {[1, 2, 3, 4, 5, 6].map(i => (
                        <div key={i} className="p-4 rounded-xl border border-white/10 bg-gray-800/40 animate-pulse">
                            <div className="flex items-start justify-between mb-2">
                                <div className="flex items-center gap-2">
                                    <div className="w-4 h-4 bg-gray-700 rounded-full" />
                                    <div className="h-5 bg-gray-700 rounded w-24" />
                                </div>
                            </div>
                            <div className="h-4 bg-gray-700 rounded w-full mb-2" />
                            <div className="h-4 bg-gray-700 rounded w-2/3 mb-4" />
                            <div className="flex gap-1">
                                <div className="h-5 bg-gray-700 rounded-full w-12" />
                                <div className="h-5 bg-gray-700 rounded-full w-16" />
                            </div>
                        </div>
                    ))}
                </div>
            ) : filteredLocations.length === 0 ? (
                <EmptyState
                    icon={MapPin}
                    title="No locations yet"
                    description="Create your first location to start building your world."
                />
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {filteredLocations.map((location) => (
                        <motion.div
                            key={location.id}
                            layout
                            className="p-4 rounded-xl border border-white/10 bg-gray-800/40 hover:bg-gray-800/60 hover:border-white/20 transition-all group"
                        >
                            {location.image_path && (
                                <img
                                    src={location.image_path.startsWith('/static') ? location.image_path : assetUrl(location.image_path)}
                                    alt={location.name}
                                    className="w-full h-32 rounded-lg object-cover mb-3 border border-white/10"
                                />
                            )}
                            <div className="flex items-start justify-between mb-2">
                                <div className="flex items-center gap-2 min-w-0">
                                    <MapPin size={16} className="text-blue-400 shrink-0" />
                                    <h3 className="font-semibold text-white truncate">{location.name}</h3>
                                </div>
                                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                                    <button
                                        onClick={() => handleEdit(location)}
                                        className="p-1 text-gray-400 hover:text-white rounded"
                                        title="Edit"
                                    >
                                        <Edit3 size={12} />
                                    </button>
                                    <button
                                        onClick={() => handleDelete(location)}
                                        className="p-1 text-gray-400 hover:text-red-400 rounded"
                                        title="Delete"
                                    >
                                        <Trash2 size={12} />
                                    </button>
                                </div>
                            </div>
                            {location.description && (
                                <p className="text-sm text-gray-400 line-clamp-2 mb-2">{location.description}</p>
                            )}
                            {location.atmosphere && (
                                <p className="text-xs text-gray-500 italic mb-2 line-clamp-1">{location.atmosphere}</p>
                            )}
                            {location.tags && location.tags.length > 0 && (
                                <div className="flex flex-wrap gap-1">
                                    {location.tags.map(tag => (
                                        <span key={tag} className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-300 border border-blue-500/20">
                                            {tag}
                                        </span>
                                    ))}
                                </div>
                            )}
                        </motion.div>
                    ))}
                </div>
            )}

            <AnimatePresence>
                {showForm && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
                        onClick={(e) => e.target === e.currentTarget && resetForm()}
                    >
                        <motion.div
                            initial={{ opacity: 0, scale: 0.95, y: 10 }}
                            animate={{ opacity: 1, scale: 1, y: 0 }}
                            exit={{ opacity: 0, scale: 0.95, y: 10 }}
                            className="bg-gray-900 border border-white/10 rounded-2xl p-6 w-full max-w-lg shadow-2xl"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="flex items-center justify-between mb-4">
                                <h2 className="text-lg font-semibold text-white">
                                    {editingLocation ? 'Edit Location' : 'New Location'}
                                </h2>
                                <button onClick={resetForm} className="text-gray-400 hover:text-white">
                                    <X size={20} />
                                </button>
                            </div>
                            {FORM_FIELDS.map(field => (
                                <div key={field.key}>
                                    <FormInput
                                        label={field.label}
                                        value={form[field.key]}
                                        onChange={(e) => setForm(f => ({ ...f, [field.key]: e.target.value }))}
                                        type={field.type}
                                        placeholder={field.placeholder}
                                        required={field.required}
                                    />
                                    {field.key === 'tags' && (
                                        <div className="mb-4">
                                            <div className="flex gap-2 mb-2">
                                                <input
                                                    type="text"
                                                    value={tagInput}
                                                    onChange={(e) => setTagInput(e.target.value)}
                                                    onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addTag())}
                                                    placeholder="Add tag..."
                                                    className="flex-1 px-3 py-1.5 bg-gray-800 border border-gray-600 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                                                />
                                                <button onClick={addTag} className="px-3 py-1.5 bg-gray-700 text-white rounded-lg text-sm hover:bg-gray-600">
                                                    Add
                                                </button>
                                            </div>
                                            <div className="flex flex-wrap gap-1">
                                                {(form.tags || []).map(tag => (
                                                    <span key={tag} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-300 text-xs border border-blue-500/20">
                                                        {tag}
                                                        <button onClick={() => removeTag(tag)} className="hover:text-white">
                                                            <X size={10} />
                                                        </button>
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            ))}
                            {editingLocation && (
                                <div className="mb-4">
                                    <label className="block text-sm font-medium text-gray-300 mb-1">Image</label>
                                    <div className="flex items-center gap-3">
                                        <input
                                            ref={imageInputRef}
                                            type="file"
                                            accept="image/*"
                                            className="hidden"
                                            onChange={handleImageUpload}
                                        />
                                        {editingLocation.image_path ? (
                                            <img
                                                src={editingLocation.image_path.startsWith('/static') ? editingLocation.image_path : assetUrl(editingLocation.image_path)}
                                                alt={editingLocation.name}
                                                className="w-16 h-16 rounded-lg object-cover border border-white/10"
                                            />
                                        ) : (
                                            <div className="w-16 h-16 rounded-lg bg-gray-800 border border-white/10 flex items-center justify-center">
                                                <ImageIcon size={20} className="text-gray-600" />
                                            </div>
                                        )}
                                        <button
                                            type="button"
                                            onClick={() => imageInputRef.current?.click()}
                                            disabled={uploadingImage}
                                            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-800 text-gray-300 rounded-lg hover:bg-gray-700 transition-colors disabled:opacity-40"
                                        >
                                            {uploadingImage ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
                                            {uploadingImage ? 'Uploading...' : 'Upload'}
                                        </button>
                                    </div>
                                </div>
                            )}
                            <div className="flex gap-2 justify-end mt-4">
                                <button onClick={resetForm} className="px-4 py-2 text-gray-400 hover:text-white transition-colors">
                                    Cancel
                                </button>
                                <button
                                    onClick={handleSave}
                                    disabled={createMutation.isPending || updateMutation.isPending}
                                    className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
                                >
                                    {editingLocation ? 'Update' : 'Create'}
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
