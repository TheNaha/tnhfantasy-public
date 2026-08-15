import React, { useState, useMemo } from 'react';
import { AnimatePresence } from 'framer-motion';
import { Plus, Trash2, Play, Settings2, Wand2, Shuffle, Image as ImageIcon } from 'lucide-react';
import toast from 'react-hot-toast';

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

export default function BatchGenerate() {
    const [preset, setPreset] = useState('character_sheet');
    const [basePrompt, setBasePrompt] = useState('');
    const [charName, setCharName] = useState('');
    const [sceneName, setSceneName] = useState('');
    const [seedMode, setSeedMode] = useState('random'); // 'random' | 'fixed' | 'increment'
    const [fixedSeed, setFixedSeed] = useState('');
    const [jobs, setJobs] = useState([]);
    const [isGenerating, setIsGenerating] = useState(false);

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

                return {
                    workflow: {
                        nodes: {},
                        edges: [],
                    },
                    options: {
                        prompt,
                        seed,
                        width: 512,
                        height: 768,
                        steps: 28,
                        cfg_scale: 7,
                        sampler: 'euler',
                        scheduler: 'normal',
                        batch_size: 1,
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

            const response = await fetch('/api/generate/batch', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ workflows }),
            });

            if (!response.ok) {
                throw new Error('Batch generation failed');
            }

            const data = await response.json();
            setJobs(data.jobs || []);
            toast.success(`Created ${data.count} generation jobs`);
        } catch (e) {
            toast.error(`Failed: ${e.message}`);
        } finally {
            setIsGenerating(false);
        }
    };

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
                            <h2 className="text-sm font-semibold text-gray-300 mb-3">Batch Jobs</h2>
                            <div className="space-y-2">
                                {jobs.map((job, idx) => (
                                    <div key={job.id} className="flex items-center gap-3 p-3 bg-gray-900/50 rounded-lg border border-white/5">
                                        <span className="text-xs text-gray-500 font-mono w-6">{idx + 1}</span>
                                        <span className="flex-1 text-sm text-gray-300 truncate">{job.metadata?.prompt || 'Untitled'}</span>
                                        <span className="text-xs text-gray-500">{job.status}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
