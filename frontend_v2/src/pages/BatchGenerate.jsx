import React, { useState, useMemo, useEffect, useCallback } from 'react';
import {
    Plus,
    Trash2,
    Play,
    Settings2,
    Wand2,
    Shuffle,
    Image as ImageIcon,
    RefreshCw,
    AlertTriangle,
} from 'lucide-react';
import toast from 'react-hot-toast';
import { useQueryClient } from '@tanstack/react-query';
import { generateApi, ApiError } from '../api';
import { useModelDirectories } from '../hooks/useModelDirectories';
import { useJobStatus } from '../hooks/useJobStatus';
import { assetUrl } from '../utils/assetUrl';
import useSettingsStore from '../store/settingsStore';
import { useGeneratorStore } from '../store/generatorStore';
import { SAMPLERS, SCHEDULERS } from '../constants/generation';
import { withCurrentOption } from '../constants/options';
import NumberInput from '../components/common/NumberInput';
import BatchPresetEditor from '../components/generator/BatchPresetEditor';
import {
    BATCH_SIZE_OPTIONS,
    MAX_BATCH_WORKFLOWS,
    batchImageCount,
    batchLimitMessage,
    describeMissingModels,
    exceedsBatchLimit,
    findMissingModels,
    lorasFromSelectedLoras,
    lorasToRequestOptions,
    lorasToSelectedLoras,
    resolvePrompts,
    useBatchPresets,
} from '../hooks/useBatchPresets';

/**
 * Baked presets. Read-only starting points: they are never mutated and never
 * deleted, and the page offers "Duplicate to mine" over each so a user gets an
 * editable copy that owns its own prompt list and LoRA weights.
 */
const PRESETS = {
    character_sheet: {
        name: 'Character Sheet',
        description: 'Generate multiple angles/expressions of a character',
        prompts: [
            'portrait of {char}, front view, neutral expression',
            'portrait of {char}, side profile, neutral expression',
            'portrait of {char}, three-quarter view, smiling',
            'portrait of {char}, close-up, detailed face',
        ],
    },
    scene_variations: {
        name: 'Scene Variations',
        description: 'Same scene with different styles/compositions',
        prompts: [
            'wide shot of {scene}, cinematic',
            'medium shot of {scene}, dramatic lighting',
            'close-up of {scene}, intimate',
            'bird\'s eye view of {scene}, epic',
        ],
    },
    concept_grid: {
        name: 'Concept Grid',
        description: 'Explore different concepts for a prompt',
        prompts: [
            '{prompt}, style A',
            '{prompt}, style B',
            '{prompt}, style C',
            '{prompt}, style D',
        ],
    },
    custom: {
        name: 'Custom',
        description: 'Your own prompt list — one prompt per line',
        prompts: [],
    },
};

const BAKED_KEYS = Object.keys(PRESETS);

const MODEL_DIRECTORY_REQUESTS = [
    { key: 'checkpoints', directory: 'models/checkpoints', label: 'checkpoints' },
    { key: 'loras', directory: 'models/loras', label: 'loras' },
    { key: 'vaeModels', directory: 'models/vae', label: 'VAE models' },
];

const TERMINAL_STATUSES = ['completed', 'failed', 'error', 'cancelled'];

// One identity for "no models". An inline `|| []` is a new array on every
// render, which is what put these three lists in five `exhaustive-deps`
// warnings: `checkpoints` and `installedLoras` feed two memos and two
// callbacks, all of which therefore recomputed on every render of this page.
const NO_MODELS = [];

function findModelByName(models, name) {
    if (!name) return null;
    return models.find((model) => model.name === name) || { name };
}

export default function BatchGenerate() {
    const queryClient = useQueryClient();

    // Every generation control is read from the generator store — the same
    // store Simple Generate writes to. That is the parity: the two pages
    // cannot disagree, and there is no second copy of `steps` sitting in local
    // state to drift out of sync with the payload that is actually submitted.
    const steps = useGeneratorStore((state) => state.steps);
    const setSteps = useGeneratorStore((state) => state.setSteps);
    const cfg = useGeneratorStore((state) => state.cfg);
    const setCfg = useGeneratorStore((state) => state.setCfg);
    const sampler = useGeneratorStore((state) => state.sampler);
    const setSampler = useGeneratorStore((state) => state.setSampler);
    const scheduler = useGeneratorStore((state) => state.scheduler);
    const setScheduler = useGeneratorStore((state) => state.setScheduler);
    const clipSkip = useGeneratorStore((state) => state.clipSkip);
    const setClipSkip = useGeneratorStore((state) => state.setClipSkip);
    const seed = useGeneratorStore((state) => state.seed);
    const setSeed = useGeneratorStore((state) => state.setSeed);
    const randomizeSeed = useGeneratorStore((state) => state.randomizeSeed);
    const negativePrompt = useGeneratorStore((state) => state.negativePrompt);
    const setNegativePrompt = useGeneratorStore((state) => state.setNegativePrompt);
    const width = useGeneratorStore((state) => state.width);
    const setWidth = useGeneratorStore((state) => state.setWidth);
    const height = useGeneratorStore((state) => state.height);
    const setHeight = useGeneratorStore((state) => state.setHeight);
    const batchSize = useGeneratorStore((state) => state.batchSize);
    const setBatchSize = useGeneratorStore((state) => state.setBatchSize);
    const selectedCheckpoint = useGeneratorStore((state) => state.selectedCheckpoint);
    const setSelectedCheckpoint = useGeneratorStore((state) => state.setSelectedCheckpoint);
    const selectedVae = useGeneratorStore((state) => state.selectedVae);
    const setSelectedVae = useGeneratorStore((state) => state.setSelectedVae);
    const selectedLoras = useGeneratorStore((state) => state.selectedLoras);
    const setSelectedLoras = useGeneratorStore((state) => state.setSelectedLoras);
    const addLora = useGeneratorStore((state) => state.addLora);
    const removeLora = useGeneratorStore((state) => state.removeLora);
    const updateLora = useGeneratorStore((state) => state.updateLora);

    const autoRandomizeSeed = useSettingsStore((state) => state.settings.generator.autoRandomizeSeed);
    const updateSetting = useSettingsStore((state) => state.updateSetting);

    const { modelsByKey, loading: modelsLoading } = useModelDirectories(MODEL_DIRECTORY_REQUESTS);
    const checkpoints = modelsByKey.checkpoints ?? NO_MODELS;
    const installedLoras = modelsByKey.loras ?? NO_MODELS;
    const vaeModels = modelsByKey.vaeModels ?? NO_MODELS;

    const {
        presets,
        getPreset,
        savePreset,
        renamePreset,
        duplicatePreset,
        deletePreset,
        exportPreset,
        importPresetFile,
    } = useBatchPresets();

    // The live prompt list is the single source of truth for the template. A
    // baked preset seeds it, a user preset replaces it, and the editor writes
    // to it — so "what will be generated" is never derived from a preset the
    // page forgot to apply.
    const [bakedType, setBakedType] = useState('character_sheet');
    const [activePresetName, setActivePresetName] = useState(null);
    const [prompts, setPrompts] = useState(() => [...PRESETS.character_sheet.prompts]);
    const [basePrompt, setBasePrompt] = useState(() => {
        if (typeof window !== 'undefined') {
            const stored = sessionStorage.getItem('tnhcomfy_batch_prompt');
            if (stored) {
                sessionStorage.removeItem('tnhcomfy_batch_prompt');
            }
            return stored || '';
        }
        return '';
    });
    const [charName, setCharName] = useState('');
    const [sceneName, setSceneName] = useState('');
    const [seedMode, setSeedMode] = useState('random'); // 'random' | 'fixed' | 'increment'
    const [jobIds, setJobIds] = useState([]);
    const [settledCount, setSettledCount] = useState(0);
    const [isGenerating, setIsGenerating] = useState(false);

    const checkpointName = selectedCheckpoint?.name || '';
    const activePreset = activePresetName ? getPreset(activePresetName) : null;

    const generatedPrompts = useMemo(
        () => resolvePrompts(prompts, { charName, sceneName, basePrompt }),
        [prompts, charName, sceneName, basePrompt]
    );

    const totalImages = batchImageCount(generatedPrompts.length, batchSize);
    // The backend bounds the number of *workflow entries*, not the images they
    // render, so that is what the page bounds too.
    const overLimit = exceedsBatchLimit(generatedPrompts.length);
    const limitMessage = overLimit ? batchLimitMessage(generatedPrompts.length) : null;

    // Install check against the same file lists ModelSelector reads through
    // useModelDirectories, so a preset saved on another machine (or after a
    // model was deleted) says so here rather than failing at render time.
    const missing = useMemo(
        () => findMissingModels(
            { checkpoint: checkpointName, loras: lorasFromSelectedLoras(selectedLoras) },
            { checkpoints, loras: installedLoras }
        ),
        [checkpointName, selectedLoras, checkpoints, installedLoras]
    );
    const showMissingWarning = !modelsLoading && missing.hasMissing;

    const matchesSizeOption = useMemo(
        () => BATCH_SIZE_OPTIONS.some((size) => size.width === width && size.height === height),
        [width, height]
    );
    const sizeLabel = useMemo(() => {
        const match = BATCH_SIZE_OPTIONS.find((size) => size.width === width && size.height === height);
        return match ? match.label : 'Custom';
    }, [width, height]);

    const checkpointOptions = useMemo(() => {
        const options = checkpoints.map((model) => ({
            name: model.name,
            label: model.display_name || model.name,
        }));
        // Keep a not-installed selection visible and labelled rather than
        // silently blanking the control, which is what a plain <select> does.
        if (checkpointName && !checkpoints.some((model) => model.name === checkpointName)) {
            options.push({ name: checkpointName, label: `${checkpointName} (not installed)` });
        }
        return options;
    }, [checkpoints, checkpointName]);

    const resolveSeedForIndex = useCallback((index) => {
        if (seedMode === 'random') return Math.floor(Math.random() * 2 ** 32);
        const base = Number(seed) || 0;
        return seedMode === 'increment' ? base + index : base;
    }, [seedMode, seed]);

    const buildWorkflows = useCallback(() => {
        // `loras` is narrowed to the backend's LoraOption shape on purpose:
        // selectedLoras carries preview images and CivitAI metadata, and
        // multiplying that across every entry of the batch is a large request
        // body for fields Pydantic would drop anyway.
        const requestLoras = lorasToRequestOptions(lorasFromSelectedLoras(selectedLoras));
        const batchPreset = activePresetName || bakedType;
        return generatedPrompts.map((prompt, idx) => {
            const jobSeed = resolveSeedForIndex(idx);
            return {
                workflow: { nodes: {}, edges: [] },
                options: {
                    mode: 't2i',
                    prompt,
                    negativePrompt,
                    seed: jobSeed,
                    width,
                    height,
                    steps,
                    cfg,
                    sampler,
                    scheduler,
                    clipSkip,
                    batchSize,
                    loras: requestLoras,
                    vae: selectedVae || 'Baked in',
                    ...(checkpointName ? { checkpoint: checkpointName } : {}),
                },
                metadata: {
                    prompt,
                    negativePrompt,
                    seed: jobSeed,
                    width,
                    height,
                    steps,
                    cfg,
                    sampler,
                    scheduler,
                    clipSkip,
                    loras: requestLoras,
                    checkpoint: checkpointName || null,
                    vae: selectedVae,
                    batch_index: idx,
                    batch_total: generatedPrompts.length,
                    batch_preset: batchPreset,
                },
            };
        });
    }, [
        generatedPrompts, resolveSeedForIndex, negativePrompt, width, height, steps, cfg,
        sampler, scheduler, clipSkip, batchSize, selectedLoras, selectedVae, checkpointName,
        activePresetName, bakedType,
    ]);

    const handleGenerate = async () => {
        // Defence in depth: the button is disabled while over the limit, but a
        // stale render must never be able to fire an oversized request.
        if (overLimit) {
            toast.error(limitMessage);
            return;
        }
        if (!generatedPrompts.some((prompt) => prompt.trim())) {
            toast.error('Please fill in required fields');
            return;
        }

        setIsGenerating(true);
        try {
            const workflows = buildWorkflows();
            const data = await generateApi.batch(workflows);
            const created = data.jobs || [];
            created.forEach((job) => queryClient.setQueryData(['jobs', job.id], job));
            setJobIds(created.map((job) => job.id));
            setSettledCount(0);
            toast.success(`Created ${created.length} generation jobs`);
        } catch (e) {
            if (e instanceof ApiError) {
                toast.error(e.message || 'Batch generation failed');
            } else {
                toast.error(`Failed: ${e.message}`);
            }
        } finally {
            setIsGenerating(false);
        }
    };

    /** Everything a preset owns, read from the live form (generator store + local state). */
    const captureCurrentDraft = useCallback((name) => ({
        name,
        bakedType,
        prompts,
        basePrompt,
        charName,
        sceneName,
        seedMode,
        negativePrompt,
        steps,
        cfg,
        sampler,
        scheduler,
        clipSkip,
        batchSize,
        width,
        height,
        checkpoint: checkpointName,
        vae: selectedVae,
        loras: lorasFromSelectedLoras(selectedLoras),
    }), [
        bakedType, prompts, basePrompt, charName, sceneName, seedMode, negativePrompt, steps,
        cfg, sampler, scheduler, clipSkip, batchSize, width, height, checkpointName,
        selectedVae, selectedLoras,
    ]);

    const handleSavePreset = useCallback((name) => {
        const result = savePreset(name, captureCurrentDraft(name));
        if (result.ok) setActivePresetName(result.name);
        return result;
    }, [savePreset, captureCurrentDraft]);

    /**
     * A preset owns every field it can: the generation config goes back into
     * the generator store (so Simple Generate agrees) and the batch-only fields
     * into local state. Nothing is read that nothing wrote.
     */
    const handleLoadPreset = useCallback((name) => {
        const preset = getPreset(name);
        if (!preset) return;

        setActivePresetName(name);
        setBakedType(preset.bakedType);
        setPrompts([...preset.prompts]);
        setBasePrompt(preset.basePrompt);
        setCharName(preset.charName);
        setSceneName(preset.sceneName);
        setSeedMode(preset.seedMode);
        setNegativePrompt(preset.negativePrompt);
        setSteps(preset.steps);
        setCfg(preset.cfg);
        setSampler(preset.sampler);
        setScheduler(preset.scheduler);
        setClipSkip(preset.clipSkip);
        setBatchSize(preset.batchSize);
        setWidth(preset.width);
        setHeight(preset.height);
        setSelectedVae(preset.vae);
        setSelectedCheckpoint(findModelByName(checkpoints, preset.checkpoint));
        setSelectedLoras(lorasToSelectedLoras(preset.loras));
        toast.success(`Loaded preset "${name}"`);
    }, [
        getPreset, setPrompts, setBasePrompt, setCharName, setSceneName, setSeedMode,
        setNegativePrompt, setSteps, setCfg, setSampler, setScheduler, setClipSkip,
        setBatchSize, setWidth, setHeight, setSelectedVae, setSelectedCheckpoint,
        setSelectedLoras, checkpoints,
    ]);

    const handleSelectBaked = useCallback((key) => {
        setActivePresetName(null);
        setBakedType(key);
        setPrompts([...PRESETS[key].prompts]);
    }, []);

    /** "Duplicate to mine" — the baked list stays read-only, the copy is the user's. */
    const handleDuplicateBaked = useCallback((key) => {
        const name = `${PRESETS[key].name} copy`;
        const result = savePreset(name, { ...captureCurrentDraft(name), bakedType: key, prompts: [...PRESETS[key].prompts] });
        if (result.ok) {
            setActivePresetName(result.name);
            setBakedType(key);
            setPrompts([...PRESETS[key].prompts]);
            toast.success(`Duplicated to "${result.name}"`);
        } else {
            toast.error(result.error);
        }
    }, [savePreset, captureCurrentDraft]);

    const handleDuplicatePreset = useCallback((name) => {
        const result = duplicatePreset(name);
        if (result.ok) {
            setActivePresetName(result.name);
            toast.success(`Duplicated to "${result.name}"`);
        } else {
            toast.error(result.error);
        }
    }, [duplicatePreset]);

    const handleRenamePreset = useCallback((from, to) => {
        const result = renamePreset(from, to);
        if (!result.ok) {
            toast.error(result.error);
            return;
        }
        if (activePresetName === from) setActivePresetName(result.name);
        toast.success(`Renamed to "${result.name}"`);
    }, [renamePreset, activePresetName]);

    const handleDeletePreset = useCallback((name) => {
        const result = deletePreset(name);
        if (!result.ok) return;
        if (activePresetName === name) setActivePresetName(null);
        toast.success(`Deleted "${name}"`);
    }, [deletePreset, activePresetName]);

    const handleExportPreset = useCallback((name) => {
        const result = exportPreset(name);
        if (!result.ok) toast.error(result.error);
    }, [exportPreset]);

    const handleSelectCheckpoint = useCallback((name) => {
        setSelectedCheckpoint(findModelByName(checkpoints, name));
    }, [checkpoints, setSelectedCheckpoint]);

    // Job progress arrives via the global WebSocket bridge (useJobsRealtime)
    // which keeps the ['jobs', id] cache fresh; BatchJobRow reads it with
    // useJobStatus (REST polling only as socket-down fallback). The parent
    // just counts how many rows have reached a terminal state.
    const handleJobSettled = useCallback(() => {
        setSettledCount((count) => count + 1);
    }, []);

    const batchActive = jobIds.length > 0 && settledCount < jobIds.length;

    const usesCharName = prompts.some((prompt) => prompt.includes('{char}'));
    const usesSceneName = prompts.some((prompt) => prompt.includes('{scene}'));
    const usesBasePrompt = prompts.some((prompt) => prompt.includes('{prompt}'));
    const canEditPrompts = bakedType === 'custom' || Boolean(activePreset);

    return (
        <div className="p-6 max-w-5xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold text-white mb-1">Batch Generation Studio</h1>
                    <p className="text-gray-400 text-sm">Generate character sheets, scene variations, and concept grids</p>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-1 space-y-6">
                    <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                        <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
                            <Settings2 size={14} /> Baked Presets
                        </h2>
                        <div className="space-y-2">
                            {BAKED_KEYS.map((key) => {
                                const baked = PRESETS[key];
                                const isActive = !activePreset && bakedType === key;
                                return (
                                    <div
                                        key={key}
                                        className={`p-3 rounded-lg border transition-colors ${
                                            isActive ? 'border-blue-500 bg-blue-500/10' : 'border-white/10 hover:border-white/20'
                                        }`}
                                    >
                                        <button
                                            type="button"
                                            onClick={() => handleSelectBaked(key)}
                                            aria-pressed={isActive}
                                            className="w-full text-left"
                                        >
                                            <div className="font-medium text-sm text-white">{baked.name}</div>
                                            <div className="text-xs text-gray-400 mt-0.5">{baked.description}</div>
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => handleDuplicateBaked(key)}
                                            aria-label={`Duplicate ${baked.name} to my presets`}
                                            className="mt-2 flex items-center gap-1 text-2xs text-blue-400 hover:text-blue-300"
                                        >
                                            <Wand2 size={11} /> Duplicate to mine
                                        </button>
                                    </div>
                                );
                            })}
                        </div>
                    </div>

                    <BatchPresetEditor
                        presets={presets}
                        activePresetName={activePresetName}
                        installedModels={{ checkpoints, loras: installedLoras }}
                        modelsLoaded={!modelsLoading}
                        onLoad={handleLoadPreset}
                        onSaveCurrent={handleSavePreset}
                        onRename={handleRenamePreset}
                        onDuplicate={handleDuplicatePreset}
                        onDelete={handleDeletePreset}
                        onExport={handleExportPreset}
                        onImport={importPresetFile}
                    />

                    <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                        <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
                            <Shuffle size={14} /> Seed Mode
                        </h2>
                        <div className="flex gap-2 mb-3">
                            {['random', 'fixed', 'increment'].map((mode) => (
                                <button
                                    key={mode}
                                    type="button"
                                    onClick={() => setSeedMode(mode)}
                                    aria-pressed={seedMode === mode}
                                    className={`flex-1 px-2 py-1.5 text-xs rounded border transition-colors capitalize ${seedMode === mode ? 'border-blue-500 bg-blue-500/10 text-white' : 'border-white/10 text-gray-400 hover:text-white'}`}
                                >
                                    {mode}
                                </button>
                            ))}
                        </div>
                        {seedMode !== 'random' && (
                            <input
                                type="number"
                                value={seed}
                                onChange={(event) => setSeed(Number(event.target.value))}
                                placeholder="Base seed"
                                className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50 mb-3"
                            />
                        )}
                        <div className="flex items-center gap-2">
                            <button
                                type="button"
                                onClick={randomizeSeed}
                                title="Randomize seed"
                                aria-label="Randomize seed"
                                className="no-touch-padding w-10 h-10 flex items-center justify-center bg-gray-800 hover:bg-gray-700 border border-white/10 rounded-lg text-white transition-colors"
                            >
                                🎲
                            </button>
                            <label className="flex items-center gap-2 cursor-pointer">
                                <input
                                    type="checkbox"
                                    checked={autoRandomizeSeed}
                                    onChange={(event) => {
                                        updateSetting('generator', 'autoRandomizeSeed', event.target.checked);
                                        if (event.target.checked) setSeedMode('random');
                                    }}
                                    className="w-3.5 h-3.5 rounded bg-gray-800 border-white/20 text-blue-500"
                                />
                                <span className="text-xs text-gray-400">Auto-randomize (shared with Simple Generate)</span>
                            </label>
                        </div>
                    </div>

                    <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                        <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
                            <ImageIcon size={14} /> Models
                        </h2>
                        <label className="block text-xs text-gray-400 mb-1" htmlFor="batch-checkpoint">Checkpoint</label>
                        <select
                            id="batch-checkpoint"
                            value={checkpointName}
                            onChange={(event) => handleSelectCheckpoint(event.target.value)}
                            className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50 mb-3"
                        >
                            <option value="">Auto (default)</option>
                            {checkpointOptions.map((option) => (
                                <option key={option.name} value={option.name}>{option.label}</option>
                            ))}
                        </select>

                        <label className="block text-xs text-gray-400 mb-1" htmlFor="batch-vae">VAE</label>
                        <select
                            id="batch-vae"
                            value={selectedVae || 'Baked in'}
                            onChange={(event) => setSelectedVae(event.target.value)}
                            className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50 mb-3"
                        >
                            <option value="Baked in">Baked in (Default)</option>
                            {vaeModels.map((model) => (
                                <option key={model.name} value={model.name}>{model.name}</option>
                            ))}
                        </select>

                        <div className="flex justify-between items-center mb-1">
                            <label className="text-xs text-gray-400">LoRAs</label>
                            <button
                                type="button"
                                onClick={addLora}
                                className="text-xs flex items-center gap-1 text-blue-400 hover:text-blue-300"
                            >
                                <Plus size={14} /> Add LoRA
                            </button>
                        </div>
                        {selectedLoras.length === 0 ? (
                            <p className="text-2xs text-gray-500">No LoRAs. A preset saves its own per-LoRA weights.</p>
                        ) : (
                            <div className="space-y-2">
                                {selectedLoras.map((lora, index) => {
                                    const loraInstalled = installedLoras.some((model) => model.name === lora.name);
                                    return (
                                        <div key={index} className="bg-gray-900/40 rounded-lg border border-white/10 p-2 space-y-1.5">
                                            <div className="flex items-center gap-1">
                                                <select
                                                    value={lora.name || ''}
                                                    onChange={(event) => {
                                                        const model = installedLoras.find((item) => item.name === event.target.value);
                                                        updateLora(index, 'model', model || { name: event.target.value });
                                                    }}
                                                    aria-label={`LoRA ${index + 1} model`}
                                                    className="flex-1 min-w-0 bg-gray-800 border border-white/10 rounded px-1.5 py-1 text-2xs text-white focus:border-blue-500 outline-none"
                                                >
                                                    <option value="">Select LoRA...</option>
                                                    {installedLoras.map((model) => (
                                                        <option key={model.name} value={model.name}>{model.name}</option>
                                                    ))}
                                                    {lora.name && !loraInstalled && (
                                                        <option value={lora.name}>{lora.name} (not installed)</option>
                                                    )}
                                                </select>
                                                <button
                                                    type="button"
                                                    onClick={() => removeLora(index)}
                                                    aria-label={`Remove LoRA ${index + 1}`}
                                                    className="p-1 text-gray-500 hover:text-red-400"
                                                >
                                                    <Trash2 size={14} />
                                                </button>
                                            </div>
                                            {lora.name && !loraInstalled && (
                                                <p className="text-2xs text-amber-400">Not installed</p>
                                            )}
                                            <div className="flex items-center gap-2">
                                                <input
                                                    type="range"
                                                    min={-2}
                                                    max={2}
                                                    step={0.1}
                                                    value={Math.max(-2, Math.min(2, lora.strength ?? 1))}
                                                    onChange={(event) => updateLora(index, 'strength', parseFloat(event.target.value))}
                                                    aria-label={`LoRA ${index + 1} strength slider`}
                                                    className="flex-1 min-w-0 h-1.5 accent-blue-500 touch-none"
                                                />
                                                <input
                                                    type="number"
                                                    step={0.1}
                                                    value={lora.strength ?? 1}
                                                    onChange={(event) => updateLora(index, 'strength', parseFloat(event.target.value) || 0)}
                                                    aria-label={`LoRA ${index + 1} strength`}
                                                    className="w-14 bg-gray-800 border border-white/10 rounded px-1.5 py-0.5 text-xs text-white text-center"
                                                />
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>

                    <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                        <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
                            <Settings2 size={14} /> Sampling
                        </h2>
                        <div className="space-y-3">
                            <NumberInput
                                label="Steps"
                                value={steps}
                                onChange={(value) => {
                                    const parsed = Number(value);
                                    if (Number.isFinite(parsed)) setSteps(Math.max(1, Math.round(parsed)));
                                }}
                                min={1}
                                max={150}
                            />
                            <NumberInput
                                label="CFG"
                                value={cfg}
                                onChange={(value) => {
                                    const parsed = Number(value);
                                    if (Number.isFinite(parsed)) setCfg(Math.max(0, parsed));
                                }}
                                min={0}
                                max={30}
                                step={0.5}
                            />
                            <NumberInput
                                label="Clip Skip"
                                value={clipSkip || 1}
                                onChange={(value) => {
                                    const parsed = Number(value);
                                    if (Number.isFinite(parsed)) setClipSkip(Math.max(1, Math.min(4, Math.round(parsed))));
                                }}
                                min={1}
                                max={4}
                            />
                            <div>
                                <label className="block text-xs text-gray-400 mb-1" htmlFor="batch-sampler">Sampler</label>
                                <select
                                    id="batch-sampler"
                                    value={sampler}
                                    onChange={(event) => setSampler(event.target.value)}
                                    className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50"
                                >
                                    {withCurrentOption(SAMPLERS, sampler).map((option) => (
                                        <option key={option} value={option}>{option}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="block text-xs text-gray-400 mb-1" htmlFor="batch-scheduler">Scheduler</label>
                                <select
                                    id="batch-scheduler"
                                    value={scheduler}
                                    onChange={(event) => setScheduler(event.target.value)}
                                    className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50"
                                >
                                    {withCurrentOption(SCHEDULERS, scheduler).map((option) => (
                                        <option key={option} value={option}>{option}</option>
                                    ))}
                                </select>
                            </div>
                        </div>
                    </div>

                    <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                        <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
                            <ImageIcon size={14} /> Settings
                        </h2>

                        <label className="block text-xs text-gray-400 mb-1" htmlFor="batch-canvas">Canvas Size</label>
                        <select
                            id="batch-canvas"
                            value={matchesSizeOption ? `${width}x${height}` : 'custom'}
                            onChange={(event) => {
                                const [nextWidth, nextHeight] = event.target.value.split('x').map(Number);
                                if (nextWidth && nextHeight) {
                                    setWidth(nextWidth);
                                    setHeight(nextHeight);
                                }
                            }}
                            className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50 mb-3"
                        >
                            {matchesSizeOption ? null : (
                                <option value="custom">Custom ({width}×{height})</option>
                            )}
                            {BATCH_SIZE_OPTIONS.map((size) => (
                                <option key={size.label} value={`${size.width}x${size.height}`}>{size.label}</option>
                            ))}
                        </select>

                        <div className="grid grid-cols-2 gap-3 mb-3">
                            <div>
                                <label className="block text-xs text-gray-400 mb-1" htmlFor="batch-width">Width</label>
                                <input
                                    id="batch-width"
                                    type="number"
                                    value={width}
                                    onChange={(event) => setWidth(Number(event.target.value) || 64)}
                                    className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50"
                                />
                            </div>
                            <div>
                                <label className="block text-xs text-gray-400 mb-1" htmlFor="batch-height">Height</label>
                                <input
                                    id="batch-height"
                                    type="number"
                                    value={height}
                                    onChange={(event) => setHeight(Number(event.target.value) || 64)}
                                    className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50"
                                />
                            </div>
                        </div>

                        <label className="block text-xs text-gray-400 mb-1" htmlFor="batch-per-image">Batch Size (images per prompt)</label>
                        <input
                            id="batch-per-image"
                            type="number"
                            min={1}
                            max={16}
                            value={batchSize}
                            onChange={(event) => setBatchSize(Math.max(1, Math.min(16, parseInt(event.target.value, 10) || 1)))}
                            className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50 mb-3"
                        />

                        <label className="block text-xs text-gray-400 mb-1" htmlFor="batch-negative">Negative Prompt</label>
                        <textarea
                            id="batch-negative"
                            value={negativePrompt}
                            onChange={(event) => setNegativePrompt(event.target.value)}
                            placeholder="Optional. Things to avoid in all batch images."
                            rows={2}
                            className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50 resize-none"
                        />
                    </div>
                </div>

                <div className="lg:col-span-2 space-y-6">
                    {showMissingWarning && (
                        <div role="alert" className="flex items-start gap-2 p-4 rounded-xl border border-amber-500/40 bg-amber-500/10">
                            <AlertTriangle size={16} className="text-amber-400 mt-0.5 flex-shrink-0" />
                            <div className="text-sm text-amber-200">
                                <p className="font-semibold">Not installed: {describeMissingModels(missing)}</p>
                                <p className="text-xs text-amber-300/80 mt-0.5">
                                    The jobs will still be created, but cannot resolve that model. Install it, or
                                    clear the reference here and in the preset.
                                </p>
                            </div>
                        </div>
                    )}

                    {(usesCharName || usesSceneName || usesBasePrompt) && (
                        <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5 space-y-4">
                            {usesCharName && (
                                <div>
                                    <h2 className="text-sm font-semibold text-gray-300 mb-3">Character Name</h2>
                                    <input
                                        type="text"
                                        value={charName}
                                        onChange={(event) => setCharName(event.target.value)}
                                        aria-label="Character name" placeholder="e.g. Elara Moonwhisper"
                                        className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                                    />
                                </div>
                            )}
                            {usesSceneName && (
                                <div>
                                    <h2 className="text-sm font-semibold text-gray-300 mb-3">Scene Name</h2>
                                    <input
                                        type="text"
                                        value={sceneName}
                                        onChange={(event) => setSceneName(event.target.value)}
                                        placeholder="e.g. Enchanted Forest"
                                        className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                                    />
                                </div>
                            )}
                            {usesBasePrompt && (
                                <div>
                                    <h2 className="text-sm font-semibold text-gray-300 mb-3">Base Prompt</h2>
                                    <textarea
                                        value={basePrompt}
                                        onChange={(event) => setBasePrompt(event.target.value)}
                                        placeholder="e.g. a futuristic cityscape at sunset"
                                        rows={3}
                                        className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50 resize-none"
                                    />
                                </div>
                            )}
                        </div>
                    )}

                    {canEditPrompts && (
                        <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                            <h2 className="text-sm font-semibold text-gray-300 mb-3">Prompts (one per line)</h2>
                            <textarea
                                value={prompts.join('\n')}
                                onChange={(event) => setPrompts(
                                    event.target.value.split('\n').map((line) => line.trim()).filter(Boolean)
                                )}
                                placeholder={'portrait of {char}, front view\nfull body of {char}, action pose'}
                                rows={5}
                                aria-label="Custom prompt list"
                                className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50 resize-none font-mono text-xs"
                            />
                            <p className="text-2xs text-gray-500 mt-1">
                                {'{char}'}, {'{scene}'} and {'{prompt}'} are substituted per image.
                            </p>
                        </div>
                    )}

                    <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                        <h2 className="text-sm font-semibold text-gray-300 mb-3">
                            Generated Prompts
                            <span className="ml-2 text-xs font-normal text-gray-500">
                                {sizeLabel} • {totalImages} image{totalImages === 1 ? '' : 's'}
                            </span>
                        </h2>
                        <div className="space-y-2">
                            {generatedPrompts.map((prompt, idx) => (
                                <div key={idx} className="flex items-center gap-3 p-3 bg-gray-900/50 rounded-lg border border-white/5">
                                    <span className="text-xs text-gray-500 font-mono w-6">{idx + 1}</span>
                                    <span className="flex-1 text-sm text-gray-300">{prompt}</span>
                                </div>
                            ))}
                        </div>
                        {overLimit && (
                            <p role="alert" className="mt-3 flex items-start gap-2 text-xs text-red-300 bg-red-500/10 border border-red-500/40 rounded-lg px-3 py-2">
                                <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
                                <span>{limitMessage}</span>
                            </p>
                        )}
                        <button
                            onClick={handleGenerate}
                            disabled={isGenerating || overLimit}
                            className="w-full mt-4 flex items-center justify-center gap-2 px-4 py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
                        >
                            <Play size={16} /> {isGenerating ? 'Generating...' : `Generate ${totalImages} Images`}
                        </button>
                        {overLimit && (
                            <p className="mt-2 text-2xs text-gray-500 text-center">
                                The backend accepts at most {MAX_BATCH_WORKFLOWS} workflows per batch request.
                            </p>
                        )}
                    </div>

                    {jobIds.length > 0 && (
                        <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                            <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
                                <RefreshCw size={14} className={batchActive ? 'animate-spin' : ''} /> Batch Jobs
                            </h2>
                            <div className="space-y-2">
                                {jobIds.map((jobId, idx) => (
                                    <BatchJobRow key={jobId} jobId={jobId} index={idx} onSettled={handleJobSettled} />
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

function BatchJobRow({ jobId, index, onSettled }) {
    const { data: job } = useJobStatus(jobId);
    const status = job?.status || 'queued';

    useEffect(() => {
        if (job && TERMINAL_STATUSES.includes(status)) {
            onSettled?.(jobId);
        }
    }, [job, status, jobId, onSettled]);

    const output = job?.outputs?.[0];
    const imagePath = output?.relative_path || output?.filename || output?.name || output?.content;

    return (
        <div className="flex items-center gap-3 p-3 bg-gray-900/50 rounded-lg border border-white/5">
            <span className="text-xs text-gray-500 font-mono w-6">{index + 1}</span>
            {imagePath ? (
                <img
                    src={assetUrl(imagePath)}
                    alt={job.metadata?.prompt || 'Generated image'}
                    className="w-14 h-14 object-cover rounded-md border border-white/10"
                />
            ) : (
                <div className="w-14 h-14 rounded-md border border-white/10 bg-gray-800 flex items-center justify-center">
                    <svg className="w-4 h-4 text-gray-600" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
                </div>
            )}
            <span className="flex-1 text-sm text-gray-300 truncate">{job?.metadata?.prompt || 'Untitled'}</span>
            <span className={`text-xs px-2 py-0.5 rounded-full capitalize ${status === 'completed' ? 'bg-green-500/10 text-green-400' : status === 'failed' || status === 'error' || status === 'cancelled' ? 'bg-red-500/10 text-red-400' : 'bg-blue-500/10 text-blue-400'}`}>{status}</span>
        </div>
    );
}
