/**
 * BatchPresetEditor.jsx - preset picker and CRUD for Batch Generate
 *
 * Baked presets stay read-only starting points; each one offers
 * "Duplicate to mine", which writes a user-owned copy and hands it back to the
 * page to load. Nothing here mutates the live generation form — the page does
 * that through the generator store — so there is exactly one source of truth
 * for the configuration that will be submitted.
 */

import { useRef, useState } from 'react';
import {
    AlertTriangle,
    Copy,
    Download,
    Pencil,
    Save,
    Trash2,
    Upload,
} from 'lucide-react';
import toast from 'react-hot-toast';
import {
    describeMissingModels,
    findMissingModels,
    summarizePreset,
} from '../../hooks/useBatchPresets';

function PresetRow({
    preset,
    isActive,
    installed,
    onLoad,
    onDuplicate,
    onRename,
    onDelete,
    onExport,
}) {
    const [isRenaming, setIsRenaming] = useState(false);
    const [draftName, setDraftName] = useState(preset.name);
    // null = follow the active preset; a boolean is an explicit user override.
    const [expandedOverride, setExpandedOverride] = useState(null);
    const isExpanded = expandedOverride === null ? isActive : expandedOverride;
    const missing = findMissingModels(preset, installed);

    const commitRename = () => {
        const next = draftName.trim();
        setIsRenaming(false);
        if (!next || next === preset.name) {
            setDraftName(preset.name);
            return;
        }
        onRename(preset.name, next);
    };

    return (
        <li className="rounded-lg border border-white/10 bg-gray-900/40">
            <div className="flex items-start gap-2 p-2">
                <button
                    type="button"
                    onClick={() => onLoad(preset.name)}
                    aria-pressed={isActive}
                    aria-label={`Load preset ${preset.name}`}
                    title={`Load "${preset.name}"`}
                    className={`flex-1 min-w-0 text-left px-2 py-1 rounded border transition-colors ${
                        isActive
                            ? 'border-blue-500 bg-blue-500/10'
                            : 'border-white/10 hover:border-white/20'
                    }`}
                >
                    <span className="block text-xs font-medium text-white truncate">{preset.name}</span>
                    <span className="block text-2xs text-gray-400 font-mono truncate">{summarizePreset(preset)}</span>
                </button>
                <div className="flex items-center gap-1 flex-shrink-0">
                    <button
                        type="button"
                        onClick={() => setExpandedOverride(!isExpanded)}
                        aria-label={`${isExpanded ? 'Hide' : 'Show'} details for ${preset.name}`}
                        title="Show what is in this preset"
                        className="p-1 text-gray-500 hover:text-white rounded hover:bg-white/5"
                    >
                        <Pencil size={12} />
                    </button>
                    <button
                        type="button"
                        onClick={() => onDuplicate(preset.name)}
                        aria-label={`Duplicate ${preset.name}`}
                        title="Duplicate"
                        className="p-1 text-gray-500 hover:text-blue-400 rounded hover:bg-white/5"
                    >
                        <Copy size={12} />
                    </button>
                    <button
                        type="button"
                        onClick={() => onExport(preset.name)}
                        aria-label={`Export ${preset.name} as JSON`}
                        title="Export JSON"
                        className="p-1 text-gray-500 hover:text-blue-400 rounded hover:bg-white/5"
                    >
                        <Download size={12} />
                    </button>
                    <button
                        type="button"
                        onClick={() => onDelete(preset.name)}
                        aria-label={`Delete ${preset.name}`}
                        title="Delete"
                        className="p-1 text-gray-500 hover:text-red-400 rounded hover:bg-white/5"
                    >
                        <Trash2 size={12} />
                    </button>
                </div>
            </div>

            {isExpanded && (
                <div className="px-3 pb-3 space-y-2 text-2xs text-gray-400 border-t border-white/5 pt-2">
                    {isRenaming && (
                        <div className="flex gap-1">
                            <input
                                autoFocus
                                type="text"
                                value={draftName}
                                aria-label={`Rename ${preset.name}`}
                                onChange={(event) => setDraftName(event.target.value)}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter') commitRename();
                                    if (event.key === 'Escape') {
                                        setDraftName(preset.name);
                                        setIsRenaming(false);
                                    }
                                }}
                                className="flex-1 bg-gray-900 border border-gray-700 rounded px-1.5 py-1 text-xs text-white focus:border-blue-500 outline-none"
                            />
                            <button
                                type="button"
                                onClick={commitRename}
                                aria-label="Confirm rename"
                                className="px-1.5 py-1 bg-blue-600 hover:bg-blue-500 text-white text-2xs rounded"
                            >
                                <Save size={11} />
                            </button>
                        </div>
                    )}
                    <div>
                        <span className="text-gray-500">Prompts ({preset.prompts.length}):</span>
                        {preset.prompts.length === 0
                            ? <span className="text-amber-400"> none — this preset expands over no prompts</span>
                            : preset.prompts.map((prompt, index) => (
                                <div key={index} className="truncate text-gray-300">• {prompt}</div>
                            ))}
                    </div>
                    <div>
                        <span className="text-gray-500">Checkpoint:</span>{' '}
                        <span className="text-gray-300">{preset.checkpoint || 'Auto (backend default)'}</span>
                    </div>
                    <div>
                        <span className="text-gray-500">VAE:</span>{' '}
                        <span className="text-gray-300">{preset.vae}</span>
                    </div>
                    <div>
                        <span className="text-gray-500">LoRAs ({preset.loras.length}):</span>
                        {preset.loras.length === 0
                            ? <span className="text-gray-500"> none</span>
                            : preset.loras.map((lora) => (
                                <div key={lora.filename} className="truncate text-gray-300">
                                    • {lora.filename} <span className="font-mono text-blue-300">× {lora.strength}</span>
                                </div>
                            ))}
                    </div>
                    <button
                        type="button"
                        onClick={() => { setDraftName(preset.name); setIsRenaming(true); }}
                        aria-label={`Rename preset ${preset.name}`}
                        className="text-2xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
                    >
                        <Pencil size={10} /> Rename
                    </button>
                </div>
            )}

            {missing.hasMissing && (
                <p
                    role="alert"
                    className="mx-2 mb-2 flex items-start gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-2xs text-amber-300"
                >
                    <AlertTriangle size={11} className="mt-0.5 flex-shrink-0" />
                    <span>Not installed: {describeMissingModels(missing)}</span>
                </p>
            )}
        </li>
    );
}

export default function BatchPresetEditor({
    presets = [],
    activePresetName = null,
    installedModels = {},
    modelsLoaded = false,
    onLoad,
    onSaveCurrent,
    onRename,
    onDuplicate,
    onDelete,
    onExport,
    onImport,
}) {
    const [nameDraft, setNameDraft] = useState('');
    const fileInputRef = useRef(null);

    const handleSave = () => {
        const result = onSaveCurrent(nameDraft);
        if (result?.ok) {
            setNameDraft('');
            toast.success(result.replaced ? `Preset "${result.name}" updated` : `Preset "${result.name}" saved`);
        } else if (result?.error) {
            toast.error(result.error);
        }
    };

    const handleImportClick = () => fileInputRef.current?.click();

    const handleFileChange = async (event) => {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (!file) return;
        const result = await onImport(file);
        if (result?.ok) {
            toast.success(`Imported preset "${result.name}"`);
        } else {
            toast.error(result?.error || 'Import failed');
        }
    };

    const installed = modelsLoaded ? installedModels : { checkpoints: [], loras: [] };

    return (
        <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
                    <Save size={14} /> My Presets
                </h2>
                <button
                    type="button"
                    onClick={handleImportClick}
                    className="flex items-center gap-1 text-2xs text-blue-400 hover:text-blue-300"
                >
                    <Upload size={11} /> Import
                </button>
            </div>
            <input
                ref={fileInputRef}
                type="file"
                accept="application/json,.json"
                onChange={handleFileChange}
                aria-label="Import preset JSON file"
                className="hidden"
            />

            {presets.length === 0 ? (
                <p className="text-2xs text-gray-500">
                    No saved presets yet. Save the current setup below, or duplicate a baked one.
                </p>
            ) : (
                <ul className="space-y-2">
                    {presets.map((preset) => (
                        <PresetRow
                            key={preset.name}
                            preset={preset}
                            isActive={preset.name === activePresetName}
                            installed={installed}
                            onLoad={onLoad}
                            onDuplicate={onDuplicate}
                            onRename={onRename}
                            onDelete={onDelete}
                            onExport={onExport}
                        />
                    ))}
                </ul>
            )}

            <div className="pt-3 border-t border-white/10 space-y-2">
                <label
                    htmlFor="batch-preset-name"
                    className="block text-2xs font-bold text-gray-500 uppercase tracking-widest"
                >
                    {activePresetName ? `Update "${activePresetName}"` : 'Save current setup as preset'}
                </label>
                <div className="flex gap-2">
                    <input
                        id="batch-preset-name"
                        type="text"
                        value={nameDraft}
                        onChange={(event) => setNameDraft(event.target.value)}
                        placeholder="Preset name"
                        className="flex-1 px-2 py-1.5 text-xs bg-gray-900 border border-gray-700 rounded text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500"
                    />
                    <button
                        type="button"
                        onClick={handleSave}
                        disabled={!nameDraft.trim()}
                        className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-500 disabled:opacity-50 transition-colors"
                    >
                        Save
                    </button>
                    {activePresetName && (
                        <button
                            type="button"
                            onClick={() => onSaveCurrent(activePresetName)}
                            className="px-3 py-1.5 text-xs bg-gray-700 text-gray-200 rounded hover:bg-gray-600 transition-colors"
                        >
                            Update
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
}

export { PresetRow };
