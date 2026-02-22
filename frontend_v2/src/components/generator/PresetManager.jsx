import { useState } from 'react';
import { Save, Trash2, Settings, ChevronDown, Check, Plus, X } from 'lucide-react';
import { useGeneratorStore } from '../../store/generatorStore';
import toast from 'react-hot-toast';
import { useConfirmation } from '../../context/ConfirmationContext';

/**
 * Component to manage parameter presets
 */
export const PresetManager = () => {
    const {
        savedPresets,
        addPreset,
        removePreset,
        setAll,
        // Current params to save
        steps, cfg, sampler, scheduler, width, height,
        hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps
    } = useGeneratorStore();

    const [isOpen, setIsOpen] = useState(false);
    const [showSaveForm, setShowSaveForm] = useState(false);
    const [newPresetName, setNewPresetName] = useState('');
    const [newPresetDesc, setNewPresetDesc] = useState('');
    const { confirm } = useConfirmation();

    const handleSavePreset = (e) => {
        e.preventDefault();
        if (!newPresetName.trim()) {
            toast.error('Please enter a preset name');
            return;
        }

        const presetData = {
            steps, cfg, sampler, scheduler, width, height,
            hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps
        };

        addPreset({
            name: newPresetName,
            description: newPresetDesc,
            data: presetData
        });

        toast.success('Preset saved!');
        setNewPresetName('');
        setNewPresetDesc('');
        setShowSaveForm(false);
    };

    const handleLoadPreset = (preset) => {
        setAll(preset.data);
        toast.success(`Loaded preset: ${preset.name}`);
        setIsOpen(false);
    };

    const handleDeletePreset = async (e, id) => {
        e.stopPropagation();
        const confirmed = await confirm({
            title: 'Delete Preset',
            message: 'Delete this preset? This cannot be undone.',
            confirmText: 'Delete',
            isDangerous: true
        });
        if (confirmed) {
            removePreset(id);
            toast.success('Preset deleted');
        }
    };

    return (
        <div className="relative">
            {/* Trigger Button */}
            <button
                onClick={() => setIsOpen(!isOpen)}
                className="flex items-center gap-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm text-gray-300 transition-colors"
                title="Manage Presets"
            >
                <Settings size={16} />
                <span>Presets</span>
                <ChevronDown size={14} className={`transition-transform ${isOpen ? 'rotate-180' : ''}`} />
            </button>

            {/* Dropdown Menu */}
            {isOpen && (
                <>
                    <div
                        className="fixed inset-0 z-40"
                        onClick={() => setIsOpen(false)}
                    />
                    <div className="absolute right-0 mt-2 w-72 bg-gray-900 border border-gray-700 rounded-xl shadow-xl z-50 overflow-hidden">
                        {/* Header */}
                        <div className="p-3 border-b border-gray-800 flex justify-between items-center bg-gray-950/50">
                            <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Parameter Presets</span>
                            <button
                                onClick={() => setShowSaveForm(!showSaveForm)}
                                className="text-xs flex items-center gap-1 text-blue-400 hover:text-blue-300"
                            >
                                <Plus size={14} />
                                Save Current
                            </button>
                        </div>

                        {/* Save Form */}
                        {showSaveForm && (
                            <form onSubmit={handleSavePreset} className="p-3 border-b border-gray-800 bg-gray-800/50">
                                <div className="space-y-2">
                                    <input
                                        type="text"
                                        placeholder="Preset Name"
                                        value={newPresetName}
                                        onChange={(e) => setNewPresetName(e.target.value)}
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-white focus:ring-1 focus:ring-blue-500 outline-none"
                                        autoFocus
                                    />
                                    <input
                                        type="text"
                                        placeholder="Description (optional)"
                                        value={newPresetDesc}
                                        onChange={(e) => setNewPresetDesc(e.target.value)}
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-300 focus:ring-1 focus:ring-blue-500 outline-none"
                                    />
                                    <div className="flex gap-2 pt-1">
                                        <button
                                            type="submit"
                                            className="flex-1 bg-blue-600 hover:bg-blue-500 text-white text-xs py-1.5 rounded"
                                        >
                                            Save
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setShowSaveForm(false)}
                                            className="px-3 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs py-1.5 rounded"
                                        >
                                            Cancel
                                        </button>
                                    </div>
                                </div>
                            </form>
                        )}

                        {/* Presets List */}
                        <div className="max-h-64 overflow-y-auto">
                            {savedPresets.length === 0 ? (
                                <div className="p-4 text-center text-gray-500 text-sm">
                                    No presets saved
                                </div>
                            ) : (
                                <div className="divide-y divide-gray-800">
                                    {savedPresets.map(preset => (
                                        <div
                                            key={preset.id}
                                            onClick={() => handleLoadPreset(preset)}
                                            className="group p-3 hover:bg-gray-800 cursor-pointer transition-colors flex items-start justify-between"
                                        >
                                            <div className="flex-1 min-w-0 mr-2">
                                                <div className="font-medium text-sm text-gray-200 truncate">
                                                    {preset.name}
                                                </div>
                                                {preset.description && (
                                                    <div className="text-xs text-gray-500 truncate">
                                                        {preset.description}
                                                    </div>
                                                )}
                                                <div className="text-[10px] text-gray-600 mt-1 font-mono">
                                                    {preset.data.width}x{preset.data.height} • {preset.data.steps} steps
                                                </div>
                                            </div>

                                            {/* Default presets (string IDs) cannot be deleted, custom ones (numeric IDs) can */}
                                            {/* Actually let's just allow deleting any for now, or check ID type */}
                                            <button
                                                onClick={(e) => handleDeletePreset(e, preset.id)}
                                                className="opacity-0 group-hover:opacity-100 p-1.5 text-gray-500 hover:text-red-400 hover:bg-red-900/20 rounded transition-all"
                                                title="Delete Preset"
                                            >
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                </>
            )}
        </div>
    );
};

export default PresetManager;
