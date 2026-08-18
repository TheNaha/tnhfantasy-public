import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { AnimatePresence } from 'framer-motion';
import { Plus, Trash2, Play, Settings2, Wand2, Shuffle, Image as ImageIcon, RefreshCw } from 'lucide-react';
import toast from 'react-hot-toast';
import { jobsApi, generateApi, ApiError } from '../api';
import { useModelDirectories } from '../hooks/useModelDirectories';

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
};

const SIZE_OPTIONS = [
    { label: '512 × 512', width: 512, height: 512 },
    { label: '512 × 768', width: 512, height: 768 },
    { label: '768 × 768', width: 768, height: 768 },
    { label: '768 × 1024', width: 768, height: 1024 },
    { label: '1024 × 1024', width: 1024, height: 1024 },
];

const TERMINAL_STATUSES = ['completed', 'failed', 'cancelled'];

import { useQueryClient } from '@tanstack/react-query';
import useSettingsStore from '../store/settingsStore';

export default function BatchGenerate() {
    const queryClient = useQueryClient();
    const batchPresets = useSettingsStore(state => state.settings.generator?.batchPresets || {});
    const saveBatchPreset = useSettingsStore(state => state.updateSetting);
    const [preset, setPreset] = useState('character_sheet');
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
    const [fixedSeed, setFixedSeed] = useState('');
    const [jobs, setJobs] = useState([]);
    const [isGenerating, setIsGenerating] = useState(false);
    const [isPolling, setIsPolling] = useState(false);
    const [checkpoint, setCheckpoint] = useState('');
    const [negativePrompt, setNegativePrompt] = useState('');
    const [sizeKey, setSizeKey] = useState(1); // 512 × 768 default
    const [steps, setSteps] = useState(28);
    const [presetName, setPresetName] = useState('');

    const { modelsByKey } = useModelDirectories([{ key: 'checkpoints', directory: 'models/checkpoints', label: 'checkpoints' }]);
    const checkpoints = modelsByKey.checkpoints || [];

    const currentPreset = PRESETS[preset];
    const generatedPrompts = useMemo(() => {
        return currentPreset.prompts.map(p => {
            let resolved = p;
            if (preset === 'character_sheet' && charName) {
                resolved = resolved.replace('{char}', charName);
            } else if (preset === 'scene_variations' && sceneName) {
                resolved = resolved.replace('{scene}', sceneName);
            } else if (preset === 'concept_grid') {
                resolved = resolved.replace('{prompt}', basePrompt || 'untitled concept');
            }
            return resolved;
        });
    }, [preset, charName, sceneName, basePrompt, currentPreset]);

    const handleGenerate = async () => {
        if (!generatedPrompts.some(p => p)) {
            toast.error('Please fill in required fields');
            return;
        }

        setIsGenerating(true);
        try {
            const workflows = generatedPrompts.map((prompt, idx) => {
                const seed = seedMode === 'random'
                    ? Math.floor(Math.random() * 2**32)
                    : seedMode === 'fixed'
                        ? parseInt(fixedSeed) || 0
                        : (parseInt(fixedSeed) || 0) + idx;
                const size = SIZE_OPTIONS[sizeKey];

                return {
                    workflow: {
                        nodes: {},
                        edges: [],
                    },
                    options: {
                        prompt,
                        negativePrompt,
                        seed,
                        width: size.width,
                        height: size.height,
                        steps,
                        cfg: 7,
                        sampler: 'euler',
                        scheduler: 'normal',
                        batchSize: 1,
                        ...(checkpoint ? { checkpoint } : {}),
                    },
                    metadata: {
                        prompt,
                        seed,
                        batch_index: idx,
                        batch_total: generatedPrompts.length,
                        batch_preset: preset,
                    },
                };
            });

            const data = await generateApi.batch(workflows);
            setJobs(data.jobs || []);
            setIsPolling(true);
            toast.success(`Created ${data.count} generation jobs`);
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

    const handleSavePreset = useCallback(() => {
        const name = presetName.trim();
        if (!name) {
            toast.error('Enter a preset name');
            return;
        }
        const presetData = {
            preset,
            basePrompt,
            charName,
            sceneName,
            seedMode,
            negativePrompt,
            sizeKey,
            steps,
        };
        const updated = { ...batchPresets, [name]: presetData };
        saveBatchPreset('generator', 'batchPresets', updated);
        setPresetName('');
        toast.success(`Preset "${name}" saved`);
        queryClient.invalidateQueries({ queryKey: ['settings'] });
    }, [preset, basePrompt, charName, sceneName, seedMode, negativePrompt, sizeKey, steps, presetName, batchPresets, saveBatchPreset, queryClient]);

    const handleLoadPreset = useCallback((name) => {
        const p = batchPresets[name];
        if (!p) return;
        setPreset(p.preset);
        setBasePrompt(p.basePrompt || '');
        setCharName(p.charName || '');
        setSceneName(p.sceneName || '');
        setSeedMode(p.seedMode || 'random');
        setNegativePrompt(p.negativePrompt || '');
        setSizeKey(p.sizeKey ?? 1);
        setSteps(p.steps || 28);
        toast.success(`Loaded preset "${name}"`);
    }, [batchPresets]);

    useEffect(() => {
        if (!isPolling || jobs.length === 0) {
            return;
        }
        let cancelled = false;
        const timer = setInterval(async () => {
            try {
                const updated = await Promise.all(jobs.map(j => jobsApi.get(j.id)));
                if (cancelled) {
                    return;
                }
                setJobs(updated);
                if (updated.every(j => TERMINAL_STATUSES.includes(j.status))) {
                    clearInterval(timer);
                    setIsPolling(false);
                }
            } catch {
                clearInterval(timer);
                setIsPolling(false);
            }
        }, 4000);
        return () => {
            cancelled = true;
            clearInterval(timer);
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isPolling, jobs.length]);

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
                            <Settings2 size={14} /> Preset
                        </h2>
                        <div className="space-y-2">
                            {Object.entries(PRESETS).map(([key, preset]) => (
                                <button
                                    key={key}
                                    onClick={() => setPreset(key)}
                                    className={`w-full text-left p-3 rounded-lg border transition-colors ${preset === key ? 'border-blue-500 bg-blue-500/10' : 'border-white/10 hover:border-white/20'}`}
                                >
                                    <div className="font-medium text-sm text-white">{preset.name}</div>
                                    <div className="text-xs text-gray-400 mt-0.5">{preset.description}</div>
                                </button>
                            ))}
                        </div>
                        {Object.keys(batchPresets).length > 0 && (
                            <div className="mt-4 pt-4 border-t border-white/10">
                                <h3 className="text-xs font-semibold text-gray-400 mb-2">Saved Presets</h3>
                                <div className="space-y-1">
                                    {Object.keys(batchPresets).map((name) => (
                                        <div key={name} className="flex items-center gap-2">
                                            <button
                                                onClick={() => handleLoadPreset(name)}
                                                className="flex-1 text-left px-2 py-1.5 text-xs rounded border border-white/10 text-gray-300 hover:text-white hover:border-white/20 transition-colors truncate"
                                                title={name}
                                            >
                                                {name}
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                        <div className="mt-4 pt-4 border-t border-white/10">
                            <h3 className="text-xs font-semibold text-gray-400 mb-2">Save Current as Preset</h3>
                            <div className="flex gap-2">
                                <input
                                    type="text"
                                    value={presetName}
                                    onChange={(e) => setPresetName(e.target.value)}
                                    placeholder="Preset name"
                                    className="flex-1 px-2 py-1.5 text-xs bg-gray-900 border border-gray-700 rounded text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500"
                                />
                                <button
                                    onClick={handleSavePreset}
                                    disabled={!presetName.trim()}
                                    className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-500 disabled:opacity-50 transition-colors"
                                >
                                    Save
                                </button>
                            </div>
                        </div>
                    </div>

                    <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                        <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
                            <Shuffle size={14} /> Seed Mode
                        </h2>
                        <div className="flex gap-2 mb-3">
                            {['random', 'fixed', 'increment'].map(mode => (
                                <button
                                    key={mode}
                                    onClick={() => setSeedMode(mode)}
                                    className={`flex-1 px-2 py-1.5 text-xs rounded border transition-colors capitalize ${seedMode === mode ? 'border-blue-500 bg-blue-500/10 text-white' : 'border-white/10 text-gray-400 hover:text-white'}`}
                                >
                                    {mode}
                                </button>
                            ))}
                        </div>
                        {seedMode !== 'random' && (
                            <input
                                type="number"
                                value={fixedSeed}
                                onChange={(e) => setFixedSeed(e.target.value)}
                                placeholder="Base seed"
                                className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                            />
                        )}
                    </div>

                    <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                        <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
                            <ImageIcon size={14} /> Settings
                        </h2>
                        <label className="block text-xs text-gray-400 mb-1">Checkpoint</label>
                        <select
                            value={checkpoint}
                            onChange={(e) => setCheckpoint(e.target.value)}
                            className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50 mb-3"
                        >
                            <option value="">Auto (default)</option>
                            {checkpoints.map(c => (
                                <option key={c.name} value={c.name}>{c.display_name || c.name}</option>
                            ))}
                        </select>

                        <label className="block text-xs text-gray-400 mb-1">Canvas Size</label>
                        <select
                            value={sizeKey}
                            onChange={(e) => setSizeKey(Number(e.target.value))}
                            className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50 mb-3"
                        >
                            {SIZE_OPTIONS.map((s, i) => (
                                <option key={s.label} value={i}>{s.label}</option>
                            ))}
                        </select>

                        <div className="flex items-center justify-between mb-1">
                            <label className="text-xs text-gray-400">Sampling Steps</label>
                            <span className="text-xs text-gray-300 font-mono">{steps}</span>
                        </div>
                        <input
                            type="range"
                            min={10}
                            max={60}
                            value={steps}
                            onChange={(e) => setSteps(Number(e.target.value))}
                            className="w-full accent-blue-500 mb-3"
                        />

                        <label className="block text-xs text-gray-400 mb-1">Negative Prompt</label>
                        <textarea
                            value={negativePrompt}
                            onChange={(e) => setNegativePrompt(e.target.value)}
                            placeholder="Optional. Things to avoid in all batch images."
                            rows={2}
                            className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50 resize-none"
                        />
                    </div>
                </div>

                <div className="lg:col-span-2 space-y-6">
                    {(preset === 'character_sheet' || preset === 'scene_variations') && (
                        <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                            <h2 className="text-sm font-semibold text-gray-300 mb-3">
                                {preset === 'character_sheet' ? 'Character Name' : 'Scene Name'}
                            </h2>
                            <input
                                type="text"
                                value={preset === 'character_sheet' ? charName : sceneName}
                                onChange={(e) => preset === 'character_sheet' ? setCharName(e.target.value) : setSceneName(e.target.value)}
                                placeholder={preset === 'character_sheet' ? 'e.g. Elara Moonwhisper' : 'e.g. Enchanted Forest'}
                                className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                            />
                        </div>
                    )}

                    {preset === 'concept_grid' && (
                        <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                            <h2 className="text-sm font-semibold text-gray-300 mb-3">Base Prompt</h2>
                            <textarea
                                value={basePrompt}
                                onChange={(e) => setBasePrompt(e.target.value)}
                                placeholder="e.g. a futuristic cityscape at sunset"
                                rows={3}
                                className="w-full px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500/50 resize-none"
                            />
                        </div>
                    )}

                    <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                        <h2 className="text-sm font-semibold text-gray-300 mb-3">Generated Prompts</h2>
                        <div className="space-y-2">
                            {generatedPrompts.map((prompt, idx) => (
                                <div key={idx} className="flex items-center gap-3 p-3 bg-gray-900/50 rounded-lg border border-white/5">
                                    <span className="text-xs text-gray-500 font-mono w-6">{idx + 1}</span>
                                    <span className="flex-1 text-sm text-gray-300">{prompt}</span>
                                </div>
                            ))}
                        </div>
                        <button
                            onClick={handleGenerate}
                            disabled={isGenerating}
                            className="w-full mt-4 flex items-center justify-center gap-2 px-4 py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
                        >
                            <Play size={16} /> {isGenerating ? 'Generating...' : `Generate ${generatedPrompts.length} Images`}
                        </button>
                    </div>

                    {jobs.length > 0 && (
                        <div className="bg-gray-800/40 border border-white/10 rounded-xl p-5">
                            <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
                                <RefreshCw size={14} className={isPolling ? 'animate-spin' : ''} /> Batch Jobs
                            </h2>
                            <div className="space-y-2">
                                {jobs.map((job, idx) => {
                                    const imageName = job.outputs?.[0]?.content;
                                    return (
                                        <div key={job.id} className="flex items-center gap-3 p-3 bg-gray-900/50 rounded-lg border border-white/5">
                                            <span className="text-xs text-gray-500 font-mono w-6">{idx + 1}</span>
                                            {imageName ? (
                                                <img
                                                    src={`/api/view/output/${imageName}`}
                                                    alt={job.metadata?.prompt || 'Generated image'}
                                                    className="w-14 h-14 object-cover rounded-md border border-white/10"
                                                />
                                            ) : (
                                                <div className="w-14 h-14 rounded-md border border-white/10 bg-gray-800 flex items-center justify-center">
                                                    <svg className="w-4 h-4 text-gray-600" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
                                                </div>
                                            )}
                                            <span className="flex-1 text-sm text-gray-300 truncate">{job.metadata?.prompt || 'Untitled'}</span>
                                            <span className={`text-xs px-2 py-0.5 rounded-full capitalize ${job.status === 'completed' ? 'bg-green-500/10 text-green-400' : job.status === 'failed' || job.status === 'cancelled' ? 'bg-red-500/10 text-red-400' : 'bg-blue-500/10 text-blue-400'}`}>{job.status}</span>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}