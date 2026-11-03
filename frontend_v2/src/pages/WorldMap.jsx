import React, { useEffect, useMemo, useState } from 'react';
import {
    MapPin, ZoomIn, ZoomOut, Target, X, Save, Trash2,
} from 'lucide-react';
import { useLocations } from '../hooks/useLocations';
import { useWorlds } from '../hooks/useWorlds';
import { useUpdateLocation } from '../hooks/useLocations';
import { api } from '../api/client';
import toast from 'react-hot-toast';
import ModalOverlay from '../components/common/ModalOverlay';
import FormInput from '../components/common/FormInput';
import EmptyState from '../components/EmptyState';
import { QueryErrorState } from '../components/common/QueryState';

const MAP_WIDTH = 1200;
const MAP_HEIGHT = 800;

export default function WorldMap({ worldId }) {
    const { data: locations = [], isLoading, isError, error, refetch } = useLocations();
    const { data: worlds = [], isLoading: worldsLoading, isError: worldsError, error: worldsErr, refetch: refetchWorlds } = useWorlds();
    const updateLocation = useUpdateLocation();

    const [draggingLocationId, setDraggingLocationId] = useState(null);
    const [mapScale, setMapScale] = useState(1);
    const [mapOffset, setMapOffset] = useState({ x: 0, y: 0 });
    const [editingLocation, setEditingLocation] = useState(null);
    const [form, setForm] = useState({ name: '', description: '', map_x: 0.5, map_y: 0.5 });

    const worldLocations = useMemo(
        () => locations.filter((l) => l.world_id === worldId || !worldId),
        [locations, worldId]
    );

    const selectedLocation = worldLocations.find((l) => l.id === editingLocation?.id);

    const toSvgX = (nx) => (nx * MAP_WIDTH) * mapScale + mapOffset.x;
    const toSvgY = (ny) => (ny * MAP_HEIGHT) * mapScale + mapOffset.y;
    const fromSvgX = (px) => (px - mapOffset.x) / (MAP_WIDTH * mapScale);
    const fromSvgY = (py) => (py - mapOffset.y) / (MAP_HEIGHT * mapScale);

    useEffect(() => {
        if (mapScale < 0.5) setMapScale(0.5);
        if (mapScale > 3) setMapScale(3);
    }, [mapScale]);

    const handleMapClick = (e) => {
        if (e.target.tagName === 'svg') {
            setEditingLocation(null);
            const rect = e.target.getBoundingClientRect();
            const mx = (e.clientX - rect.left - mapOffset.x) / mapScale;
            const my = (e.clientY - rect.top - mapOffset.y) / mapScale;
            setForm({ name: '', description: '', map_x: fromSvgX(mx), map_y: fromSvgY(my) });
            setEditingLocation({ id: null, isNew: true });
        }
    };

    const handlePinDragEnd = async (e, location) => {
        if (!draggingLocationId) return;
        e.stopPropagation();
        const rect = e.currentTarget.getBoundingClientRect();
        const mx = (e.clientX - rect.left - mapOffset.x) / mapScale;
        const my = (e.clientY - rect.top - mapOffset.y) / mapScale;
        const nx = Math.max(0, Math.min(1, fromSvgX(mx)));
        const ny = Math.max(0, Math.min(1, fromSvgY(my)));

        try {
            await updateLocation.mutateAsync({
                id: location.id,
                map_x: nx,
                map_y: ny,
            });
            await refetch();
            toast.success(`${location.name} position updated`, { id: 'map-update' });
        } catch {
            toast.error('Failed to update position', { id: 'map-error' });
        } finally {
            setDraggingLocationId(null);
        }
    };

    const handleSave = async () => {
        const locData = {
            name: form.name.trim(),
            description: form.description.trim(),
            map_x: Math.max(0, Math.min(1, form.map_x)),
            map_y: Math.max(0, Math.min(1, form.map_y)),
            world_id: worldId || null,
        };

        try {
            if (editingLocation.isNew) {
                await api.post('/api/v2/locations', locData);
                toast.success(`${locData.name} added to map`, { id: 'map-add' });
            } else {
                await updateLocation.mutateAsync({
                    id: editingLocation.id,
                    ...locData,
                });
                toast.success(`${locData.name} updated`, { id: 'map-update' });
            }
            await refetch();
            setEditingLocation(null);
        } catch {
            toast.error('Failed to save location', { id: 'map-save-error' });
        }
    };

    const handleDelete = async () => {
        const loc = worldLocations.find((l) => l.id === editingLocation.id);
        if (!loc) return;
        if (!window.confirm(`Delete "${loc.name}" from the map?`)) return;
        try {
            await api.delete(`/api/v2/locations/${editingLocation.id}`);
            await refetch();
            setEditingLocation(null);
            toast.success(`${loc.name} removed`, { id: 'map-delete' });
        } catch {
            toast.error('Failed to delete location', { id: 'map-delete-error' });
        }
    };

    const worldName = worlds.find((w) => w.id === worldId)?.name || 'World';

    if (isLoading || worldsLoading) {
        return (
            <div className="flex h-full items-center justify-center text-gray-400">
                Loading world map…
            </div>
        );
    }

    if (isError || worldsError) {
        return (
            <div className="flex h-full items-center justify-center p-8">
                <QueryErrorState noun={isError ? 'locations' : 'worlds'} error={error || worldsErr} onRetry={() => { refetch(); refetchWorlds(); }} />
            </div>
        );
    }

    if (worldLocations.length === 0) {
        return (
            <div className="flex h-full flex-col items-center justify-center p-8 text-center">
                <EmptyState
                    title="No locations yet"
                    description="Start building your world map by adding locations. Click anywhere on the map to place a pin."
                />
                <button
                    onClick={() => {
                        setEditingLocation({ id: null, isNew: true });
                    }}
                    className="mt-4 bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg transition-colors"
                >
                    Add First Location
                </button>
            </div>
        );
    }

    return (
        <div className="flex h-full flex-col bg-gray-900 text-white">
            <header className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-gray-800/50 shrink-0">
                <div className="flex items-center gap-2">
                    <MapPin size={18} className="text-blue-400" />
                    <h1 className="text-lg font-semibold">{worldName} — World Map</h1>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setMapScale(Math.min(3, mapScale + 0.25))}
                        className="p-2 text-gray-300 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                        title="Zoom in"
                        aria-label="Zoom in"
                    >
                        <ZoomIn size={16} />
                    </button>
                    <button
                        onClick={() => setMapScale(Math.max(0.5, mapScale - 0.25))}
                        className="p-2 text-gray-300 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                        title="Zoom out"
                        aria-label="Zoom out"
                    >
                        <ZoomOut size={16} />
                    </button>
                    <button
                        onClick={() => {
                            setMapScale(1);
                            setMapOffset({ x: 0, y: 0 });
                        }}
                        className="p-2 text-gray-300 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                        title="Reset view"
                        aria-label="Reset view"
                    >
                        <Target size={16} />
                    </button>
                </div>
            </header>

            <div className="flex-1 relative overflow-hidden bg-gray-950">
                <svg
                    width={MAP_WIDTH}
                    height={MAP_HEIGHT}
                    onClick={handleMapClick}
                    onWheel={(e) => {
                        e.preventDefault();
                        const delta = e.deltaY > 0 ? -0.1 : 0.1;
                        const newScale = Math.max(0.5, Math.min(3, mapScale + delta));
                        const rect = e.currentTarget.getBoundingClientRect();
                        const mx = e.clientX - rect.left;
                        const my = e.clientY - rect.top;
                        setMapScale(newScale);
                        setMapOffset((prev) => ({
                            x: prev.x - (mx - prev.x) / mapScale * (newScale - mapScale),
                            y: prev.y - (my - prev.y) / mapScale * (newScale - mapScale),
                        }));
                    }}
                    style={{ cursor: draggingLocationId ? 'grabbing' : 'crosshair' }}
                    className="block"
                >
                    <defs>
                        <pattern id="grid" width={100} height={100} patternUnits="userSpaceOnUse">
                            <path
                                d="M 100 0 L 0 0 0 100"
                                fill="none"
                                stroke="white"
                                strokeOpacity={0.05}
                                strokeWidth={1}
                            />
                        </pattern>
                    </defs>
                    <rect width={MAP_WIDTH} height={MAP_HEIGHT} fill="url(#grid)" />

                    {worldLocations.map((loc) => {
                        const isSelected = editingLocation?.id === loc.id;
                        const isDragging = draggingLocationId === loc.id;
                        const sx = toSvgX(loc.map_x ?? 0.5);
                        const sy = toSvgY(loc.map_y ?? 0.5);
                        return (
                            <g
                                key={loc.id}
                                transform={`translate(${sx},${sy})`}
                                onMouseDown={(e) => { e.stopPropagation(); setDraggingLocationId(loc.id); }}
                                onMouseUp={(e) => { e.stopPropagation(); handlePinDragEnd(e, loc); }}
                                onClick={() => {
                                    setEditingLocation({
                                        id: loc.id,
                                        isNew: false,
                                        name: loc.name || '',
                                        description: loc.description || '',
                                        map_x: loc.map_x ?? 0.5,
                                        map_y: loc.map_y ?? 0.5,
                                    });
                                    setForm({
                                        name: loc.name || '',
                                        description: loc.description || '',
                                        map_x: loc.map_x ?? 0.5,
                                        map_y: loc.map_y ?? 0.5,
                                    });
                                }}
                                onMouseLeave={() => setDraggingLocationId(null)}
                                style={{ cursor: 'pointer' }}
                            >
                                <circle
                                    cx={0}
                                    cy={0}
                                    r={12}
                                    fill={isSelected ? '#3b82f6' : loc.map_x ? '#ef4444' : '#94a3b8'}
                                    stroke="white"
                                    strokeWidth={2}
                                />
                                {isSelected && (
                                    <circle cx={0} cy={0} r={18} fill="none" stroke="#3b82f6" strokeWidth={2} strokeDasharray="4" />
                                )}
                                <text
                                    x={0}
                                    y={-18}
                                    textAnchor="middle"
                                    fontSize={11}
                                    fill="white"
                                    fontWeight="600"
                                    className="drop-shadow-md"
                                >
                                    {loc.name}
                                </text>
                                {isDragging && (
                                    <text
                                        x={0}
                                        y={-30}
                                        textAnchor="middle"
                                        fontSize={10}
                                        fill="white"
                                        fontWeight="600"
                                    >
                                        Drag to reposition
                                    </text>
                                )}
                            </g>
                        );
                    })}
                </svg>
            </div>

            {editingLocation && (
                <ModalOverlay onClose={() => setEditingLocation(null)} closeOnBackdrop>
                    <div className="w-full max-w-md bg-gray-900 border border-white/10 rounded-2xl shadow-2xl flex flex-col max-h-[80vh] overflow-hidden">
                        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 shrink-0">
                            <h3 className="font-bold text-white">
                                {editingLocation.isNew ? 'New Location' : 'Edit Location'}
                            </h3>
                            <button
                                onClick={() => setEditingLocation(null)}
                                className="text-gray-400 hover:text-white p-1"
                                aria-label="Close editor"
                            >
                                <X size={18} />
                            </button>
                        </div>
                        <div className="flex-1 overflow-y-auto p-6 space-y-4">
                            <FormInput
                                label="Name"
                                value={form.name}
                                onChange={(e) => setForm({ ...form, name: e.target.value })}
                                placeholder="e.g. The Arcanium"
                            />
                            <FormInput
                                label="Description"
                                value={form.description}
                                onChange={(e) => setForm({ ...form, description: e.target.value })}
                                placeholder="Describe this place…"
                                rows={3}
                            />
                            <div className="grid grid-cols-2 gap-4">
                                <FormInput
                                    label="Map X (0-1)"
                                    type="number"
                                    min={0}
                                    max={1}
                                    step={0.01}
                                    value={form.map_x}
                                    onChange={(e) => setForm({ ...form, map_x: parseFloat(e.target.value) || 0 })}
                                />
                                <FormInput
                                    label="Map Y (0-1)"
                                    type="number"
                                    min={0}
                                    max={1}
                                    step={0.01}
                                    value={form.map_y}
                                    onChange={(e) => setForm({ ...form, map_y: parseFloat(e.target.value) || 0 })}
                                />
                            </div>
                            {selectedLocation && selectedLocation.image_path && (
                                <div className="mt-4">
                                    <img
                                        src={selectedLocation.image_path}
                                        alt={selectedLocation.name}
                                        className="w-full h-32 object-cover rounded-lg border border-white/10"
                                    />
                                </div>
                            )}
                        </div>
                        <div className="px-6 py-4 border-t border-white/5 shrink-0 flex justify-end gap-2">
                            {!editingLocation.isNew && (
                                <button
                                    onClick={handleDelete}
                                    className="text-red-400 hover:text-red-300 text-sm font-medium transition-colors"
                                >
                                    <Trash2 size={16} /> Delete
                                </button>
                            )}
                            <button
                                onClick={handleSave}
                                className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg font-medium transition-colors"
                            >
                                <Save size={16} /> {editingLocation.isNew ? 'Add to Map' : 'Save'}
                            </button>
                        </div>
                    </div>
                </ModalOverlay>
            )}
        </div>
    );
}
