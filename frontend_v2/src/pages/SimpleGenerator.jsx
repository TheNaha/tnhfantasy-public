import React, { useState, useEffect, useRef } from 'react';
import { Wand2, Image as ImageIcon, Settings2, Plus, Trash2, Upload, RefreshCw, Info, Lock, Unlock, Layers, Sparkles, FolderOpen, Loader2, BookOpen, ChevronDown } from 'lucide-react';
import { WorkflowBuilder } from '../utils/workflowBuilder';
import { useGeneratorStore } from '../store/generatorStore';
import { useJobStore } from '../store/jobStore';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import ModelSelector from '../components/ModelSelector';
import ModelMetadataModal from '../components/ModelMetadataModal';
import PromptLibrary from '../components/generator/PromptLibrary';
import PresetManager from '../components/generator/PresetManager';
import GeneratorTabs from '../components/generator/GeneratorTabs';
import CollapsibleSection from '../components/CollapsibleSection';
import NumberInput from '../components/common/NumberInput';
import { useNavigate } from 'react-router-dom';
import { usePingProviders } from '../hooks/usePingProviders';
import toast from 'react-hot-toast';
import useSettingsStore, { useSettings, useUpdateSettings } from '../store/settingsStore';

// API Layer
import { filesApi, api } from '../api';
import { useWebSocket, EventTypes } from '../api/websocket';

export default function SimpleGenerator() {
    usePingProviders();
    const navigate = useNavigate();
    const settings = useSettings();
    const [generating, setGenerating] = useState(false);
    const [checkpoints, setCheckpoints] = useState([]);
    const [controlNetModels, setControlNetModels] = useState([]);
    const [upscalerModels, setUpscalerModels] = useState([]);
    const [vaeModels, setVaeModels] = useState([]);
    const [unetModels, setUnetModels] = useState([]);
    const [clipModels, setClipModels] = useState([]);
    const [embeddingModels, setEmbeddingModels] = useState([]);
    const [adetailerModels, setAdetailerModels] = useState([]);
    const [viewingMetadata, setViewingMetadata] = useState(null);
    const [currentJobId, setCurrentJobId] = useState(null);
    const [progress, setProgress] = useState(null); // { value, max, node, status }
    const [expandedTriggerGroups, setExpandedTriggerGroups] = useState({}); // { "loraIdx-groupIdx": true }

    // WebSocket Integration
    const { subscribe: on } = useWebSocket(['job']);

    // Use ref to track current job ID without triggering effect re-runs
    const currentJobIdRef = useRef(currentJobId);
    currentJobIdRef.current = currentJobId;

    useEffect(() => {
        // Listen for progress updates
        const unsubProgress = on(EventTypes.JOB_PROGRESS, (data) => {
            const jobId = currentJobIdRef.current;
            if (jobId && data.id === jobId) {
                // Determine message based on progress type
                let message = `${data.progress}%`;
                if (data.node) message = `${data.node} (${data.progress}%)`;

                setProgress({
                    value: data.progress,
                    max: 100,
                    status: 'processing',
                    node: data.message || message
                });
            }
        });

        // Listen for completion
        const unsubComplete = on(EventTypes.JOB_COMPLETED, (data) => {
            const jobId = currentJobIdRef.current;
            console.log('[WebSocket] JOB_COMPLETED event:', data.id, 'current:', jobId);
            if (jobId && data.id === jobId) {
                setGenerating(false);
                setProgress(null);
                setCurrentJobId(null);
                toast.success('Generation complete!', { icon: '✨' });

                if (settings.generator.redirectAfterGenerate) {
                    setTimeout(() => navigate('/'), settings.generator.redirectDelay);
                }
            }
        });

        // Listen for failure
        const unsubFailed = on(EventTypes.JOB_FAILED, (data) => {
            const jobId = currentJobIdRef.current;
            console.log('[WebSocket] JOB_FAILED event:', data.id, 'current:', jobId);
            if (jobId && data.id === jobId) {
                setGenerating(false);
                setProgress(null);
                setCurrentJobId(null);
                toast.error(`Generation failed: ${data.error}`);
            }
        });

        return () => {
            unsubProgress();
            unsubComplete();
            unsubFailed();
        };
    }, [navigate, settings.generator.redirectAfterGenerate, settings.generator.redirectDelay, on]);

    // Global State from Store
    const {
        prompt, negativePrompt, seed, steps, cfg, sampler, scheduler, width, height, batchSize,
        selectedCheckpoint, selectedVae, selectedClip, selectedClip2, selectedLoras, controlnets,
        hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps,
        adetailer, adetailerModel, adetailerPrompt, adetailerNegative, adetailerSteps, adetailerDenoise, adetailerInpaintMasked,
        setPrompt, setNegativePrompt, setSeed, setSteps, setCfg, setSampler, setScheduler, setWidth, setHeight, setBatchSize, setAspectRatioLocked,
        setSelectedCheckpoint, setSelectedVae, setSelectedClip, setSelectedClip2,
        setHiresFix, setHiresUpscaler, setHiresDenoise, setHiresUpscale, setHiresSteps,
        setAdetailer, setAdetailerModel, setAdetailerPrompt, setAdetailerSteps, setAdetailerDenoise, setAdetailerInpaintMasked,
        randomizeSeed, addLora, removeLora, updateLora, addControlNet, removeControlNet, updateControlNet, addTriggerWords, applySDXLSettings,
        aspectRatioLocked
    } = useGeneratorStore();

    const { connect, disconnect } = useJobStore();
    const activeJobCount = useJobStore(state => state.jobs.filter(j => j.status === 'pending' || j.status === 'running').length);

    // Settings for auto-randomize seed
    const autoRandomizeSeed = useSettingsStore(state => state.settings.generator.autoRandomizeSeed);
    const { updateSetting } = useUpdateSettings();

    // Connect to job updates
    useEffect(() => {
        connect();
        return () => disconnect();
    }, [connect, disconnect]);

    const [showPromptLibrary, setShowPromptLibrary] = useState(false);
    const [autoOpenLoraIndex, setAutoOpenLoraIndex] = useState(null); // Index of LoRA selector to auto-open

    // Keyboard shortcuts
    useKeyboardShortcuts();

    // Helper to extract embeddings from prompts
    const extractEmbeddingsFromPrompt = (positivePrompt, negativePrompt) => {
        const embeddingRegex = /embedding:([\w_-]+(?:\.\w+)?)/g;
        const positive = [];
        const negative = [];

        let match;
        while ((match = embeddingRegex.exec(positivePrompt)) !== null) {
            positive.push(match[1]);
        }
        while ((match = embeddingRegex.exec(negativePrompt)) !== null) {
            negative.push(match[1]);
        }

        return { positive, negative };
    };


    // Listen for custom events from ModelSelector
    useEffect(() => {
        const handleAddTriggerWords = (e) => addTriggerWords(e.detail);
        const handleApplySDXL = () => {
            applySDXLSettings();
            toast.success("Applied SDXL Settings!");
        };

        window.addEventListener('addTriggerWords', handleAddTriggerWords);
        window.addEventListener('applySDXLSettings', handleApplySDXL);

        return () => {
            window.removeEventListener('addTriggerWords', handleAddTriggerWords);
            window.removeEventListener('applySDXLSettings', handleApplySDXL);
        };
    }, [addTriggerWords, applySDXLSettings]);

    // Obsolete saved prompts functionality removed - using Prompt Library instead

    // Handler for Prompt Library
    const handleSelectPromptFromLibrary = (prompt) => {
        setPrompt(prompt.text);
        if (prompt.negative) {
            setNegativePrompt(prompt.negative);
        }
    };

    // Load models on mount
    useEffect(() => {
        const loadModels = async () => {
            try {
                // Load Checkpoints
                const ckptData = await filesApi.list({ directory: 'models/checkpoints' });
                setCheckpoints(ckptData.files || []);

                const cnData = await filesApi.list({ directory: 'models/controlnet' });
                setControlNetModels(cnData.files || []);

                // Load Upscalers
                const upData = await filesApi.list({ directory: 'models/upscale_models' });
                setUpscalerModels(upData.files || []);

                // Load ADetailer Models (bbox)
                const adData = await filesApi.list({ directory: 'models/ultralytics/bbox' });
                setAdetailerModels(adData.files || []);

                // Load VAEs
                const vaeData = await filesApi.list({ directory: 'models/vae' });
                setVaeModels(vaeData.files || []);

                // Load CLIP models (for Flux)
                const clipData = await filesApi.list({ directory: 'models/clip' });
                setClipModels(clipData.files || []);

                // Load UNET models (for Flux - stored separately from checkpoints)
                const unetData = await filesApi.list({ directory: 'models/unet' });
                setUnetModels(unetData.files || []);

                // Load Embeddings
                const embData = await filesApi.list({ directory: 'models/embeddings' });
                setEmbeddingModels(embData.files || []);

            } catch (e) {
                console.error("Failed to load models", e);
                toast.error("Failed to load models");
            }
        };
        loadModels();
    }, []);

    const handleAddLora = () => {
        addLora();
        // Auto-open the selector for the newly added LoRA
        setAutoOpenLoraIndex(selectedLoras.length); // Will be the new index after addLora
    };

    const handleRemoveLora = (index) => {
        removeLora(index);
    };

    const handleLoraChange = (index, field, value) => {
        updateLora(index, field, value);
    };

    // addTriggerWords is now handled by the store action directly in the effect
    // But we still need the function for the UI buttons
    // The store action is named addTriggerWords too, so it's already in scope!
    // However, the UI calls addTriggerWords(words) which matches the store signature.
    // So we don't need to redefine it, BUT we need to make sure the toast is shown.
    // The store action doesn't show toast.
    // Let's wrap it.

    const handleAddTriggerWordsUI = (words) => {
        addTriggerWords(words);
        toast.success("Added trigger words!");
    };

    // ControlNet Handlers
    const handleAddControlNet = () => {
        addControlNet(controlNetModels[0]?.name);
    };

    const handleRemoveControlNet = (index) => {
        removeControlNet(index);
    };

    const handleControlNetChange = (index, field, value) => {
        updateControlNet(index, field, value);
    };

    const handleControlNetUpload = async (index, file) => {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('path', 'input');

        const uploadPromise = api.post('/api/upload', formData);

        toast.promise(uploadPromise, {
            loading: 'Uploading image...',
            success: (data) => {
                if (data.status === 'success') {
                    handleControlNetChange(index, 'image', file.name);
                    return 'Image uploaded!';
                } else {
                    throw new Error('Upload failed');
                }
            },
            error: 'Upload failed'
        });
    };

    // const [progress, setProgress] = useState(null); // Moved to top level state

    // Helper to detect model types
    const isFluxModel = (model) => {
        const base = model?.base_model?.toLowerCase() || "";
        return base.includes('flux');
    };

    const isAuraFlowModel = (model) => {
        const base = model?.base_model?.toLowerCase() || "";
        return base.includes('aura');
    };

    const isPonyModel = (model) => {
        const base = model?.base_model?.toLowerCase() || "";
        return base.includes('pony 7') || base.includes('pony v7');
    };

    const isUnetModel = (model) => isFluxModel(model) || isAuraFlowModel(model);

// ...

    const handleGenerate = async (shouldRedirect = true) => {
        console.log('[Generate] Starting generation...');
        setGenerating(true);
        setProgress({ value: 0, max: 100, status: 'starting', node: 'Initializing...' });

        try {
            const builder = new WorkflowBuilder();
            
            // Detect if this is a UNET model (Flux or AuraFlow/Pony V7)
            const isUnet = isUnetModel(selectedCheckpoint);
            
            // Determine VAE: UNET models need explicit VAE.
            // If "Baked in" is selected, we MUST provide a default file because UNETs have no baked VAE.
            let effectiveVae = selectedVae;
            if (effectiveVae === "Baked in" && isUnet) {
                if (isFluxModel(selectedCheckpoint)) effectiveVae = "ae.safetensors";
                else if (isAuraFlowModel(selectedCheckpoint) || isPonyModel(selectedCheckpoint)) effectiveVae = "sdxl_vae.safetensors";
            }

            const workflow = builder.build({
                prompt,
                negativePrompt,
                seed,
                steps,
                cfg,
                sampler,
                scheduler,
                width,
                height,
                batchSize,
                // For UNET models: pass as unet; for standard: pass as checkpoint
                checkpoint: isUnet ? null : selectedCheckpoint?.name,
                unet: isUnet ? selectedCheckpoint?.name : null,
                clip: isUnet ? selectedClip : null,
                clip2: (isUnet && (isFluxModel(selectedCheckpoint) || isPonyModel(selectedCheckpoint))) ? selectedClip2 : null, // Flux and Pony use 2nd clip
                vae: effectiveVae,
                loras: selectedLoras,
                controlnets: controlnets,
                hiresFix,
                hiresUpscaler,
                hiresDenoise,
                hiresUpscale,
                hiresSteps,
                adetailer,
                adetailerModel,
                adetailerPrompt,
                adetailerNegative,
                adetailerSteps,
                adetailerDenoise,
                adetailerInpaintMasked,
                modelType: isFluxModel(selectedCheckpoint) ? 'flux' : (isPonyModel(selectedCheckpoint) || isAuraFlowModel(selectedCheckpoint)) ? 'sdxl' : 'sd15'
            });


            // Metadata to save with the image
            const metadata = {
                prompt,
                negativePrompt,
                seed,
                steps,
                cfg,
                sampler,
                scheduler,
                width,
                height,
                batchSize,
                checkpoint: selectedCheckpoint,
                vae: selectedVae,
                loras: selectedLoras,
                embeddings: extractEmbeddingsFromPrompt(prompt, negativePrompt),
                hiresFix,
                hiresUpscaler,
                adetailer,
                adetailerModel
            };

            console.log('[Generate] Sending POST to /api/generate...');
            const data = await api.post('/api/generate', { workflow, metadata });
            console.log('[Generate] Response received:', data);

            // Job queued successfully - reset generating state immediately
            if (data && data.id) {
                setCurrentJobId(data.id);
                toast.success('Job queued!', { icon: '⏳' });

                // Redirect to gallery if requested, otherwise stay on page
                if (shouldRedirect) {
                    navigate('/');
                }

                // Auto-randomize seed for next generation
                if (autoRandomizeSeed) {
                    randomizeSeed();
                }
            }

        } catch (e) {
            console.error('[Generate] Error:', e);
            toast.error("Error: " + e.message);
        } finally {
            // Always reset generating state after job is queued (or failed)
            setGenerating(false);
            setProgress(null);
        }
    };

    const setResolution = (w, h) => {
        setWidth(w);
        setHeight(h);
    };

    const handleDimensionChange = (type, value) => {
        const newVal = parseInt(value);
        if (isNaN(newVal)) return;

        if (aspectRatioLocked) {
            const ratio = width / height;
            if (type === 'width') {
                setWidth(newVal);
                setHeight(Math.round(newVal / ratio));
            } else {
                setHeight(newVal);
                setWidth(Math.round(newVal * ratio));
            }
        } else {
            if (type === 'width') setWidth(newVal);
            else setHeight(newVal);
        }
    };

    // Generate multiple variations with different seeds
    const [showVariationsMenu, setShowVariationsMenu] = useState(false);

    const handleGenerateVariations = async (count) => {
        setShowVariationsMenu(false);
        setGenerating(true);

        try {
            const builder = new WorkflowBuilder();
            const jobs = [];

            for (let i = 0; i < count; i++) {
                const variationSeed = Math.floor(Math.random() * Number.MAX_SAFE_INTEGER);

                const workflow = builder.build({
                    prompt,
                    negativePrompt,
                    seed: variationSeed,
                    steps,
                    cfg,
                    sampler,
                    scheduler,
                    width,
                    height,
                    batchSize,
                    checkpoint: selectedCheckpoint?.name,
                    vae: selectedVae,
                    loras: selectedLoras,
                    controlnets: controlnets,
                    hiresFix,
                    hiresUpscaler,
                    hiresDenoise,
                    hiresUpscale,
                    hiresSteps,
                    adetailer,
                    adetailerModel,
                    adetailerPrompt,
                    adetailerNegative,
                    adetailerSteps,
                    adetailerDenoise,
                    adetailerInpaintMasked
                });

                const metadata = {
                    prompt,
                    negativePrompt,
                    seed: variationSeed,
                    steps,
                    cfg,
                    sampler,
                    scheduler,
                    width,
                    height,
                    batchSize,
                    checkpoint: selectedCheckpoint,
                    vae: selectedVae,
                    loras: selectedLoras,
                    embeddings: extractEmbeddingsFromPrompt(prompt, negativePrompt),
                    hiresFix,
                    hiresUpscaler,
                    adetailer,
                    adetailerModel
                };

                jobs.push(api.post('/api/generate', { workflow, metadata }));
            }

            await Promise.all(jobs);

            toast.success(`Queued ${count} variations!`, { icon: '🎲' });

            // Auto-randomize seed for next generation
            if (autoRandomizeSeed) {
                randomizeSeed();
            }

            // Always redirect to gallery after queuing seed variations
            navigate('/');

        } catch (e) {
            console.error(e);
            toast.error("Error: " + e.message);
        } finally {
            setGenerating(false);
        }
    };

    return (
        <div className="pb-24">
            {/* Header with Tabs */}
            <div className="max-w-6xl mx-auto mb-6">
                <div className="flex justify-between items-center mb-4">
                    <h1 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-500">
                        Create
                    </h1>
                    {activeJobCount > 0 && (
                        <div className="flex items-center gap-2 bg-blue-900/30 text-blue-200 px-3 py-1.5 rounded-full text-sm border border-blue-800/50 backdrop-blur-sm">
                            <Loader2 className="animate-spin" size={14} />
                            <span>{activeJobCount} in queue</span>
                        </div>
                    )}
                </div>
                {/* Tab Navigation */}
                <GeneratorTabs />
            </div>


            <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-3 lg:gap-8">
                {/* Left Column: Settings */}
                <div className="lg:col-span-2 space-y-3 lg:space-y-6 order-last lg:order-none">


                    {/* Prompt Section */}
                    <div className="space-y-3 pb-4 border-b border-gray-800">
                        <div className="flex justify-between items-center">
                            <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2">
                                <Wand2 size={18} className="text-blue-400" />
                                Prompts
                            </h3>
                            <button
                                onClick={() => setShowPromptLibrary(true)}
                                className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs lg:text-sm rounded-lg flex items-center gap-1.5 transition-colors"
                                aria-label="Open prompt library"
                                type="button"
                            >
                                <BookOpen size={14} aria-hidden="true" />
                                <span className="hidden sm:inline">Library</span>
                                <span className="sm:hidden">Library</span>
                            </button>
                        </div>
                        <div>
                            <label className="block text-xs font-medium text-gray-400 mb-1">Positive Prompt</label>
                            <textarea
                                className="w-full bg-gray-900/50 border border-gray-700 rounded-lg p-2 lg:p-3 text-sm text-white min-h-[4rem] lg:min-h-[8rem] focus:ring-2 focus:ring-blue-500 outline-none resize-y overflow-hidden"
                                value={prompt}
                                onChange={(e) => {
                                    setPrompt(e.target.value);
                                    e.target.style.height = 'auto';
                                    e.target.style.height = e.target.scrollHeight + 'px';
                                }}
                                ref={(el) => {
                                    if (el) {
                                        el.style.height = 'auto';
                                        el.style.height = el.scrollHeight + 'px';
                                    }
                                }}
                            />
                        </div>
                        <div>
                            <label className="block text-xs font-medium text-gray-400 mb-1">Negative Prompt</label>
                            <textarea
                                className="w-full bg-gray-900/50 border border-gray-700 rounded-lg p-2 lg:p-3 text-sm text-white min-h-[3rem] lg:min-h-[5rem] focus:ring-2 focus:ring-red-500 outline-none resize-y overflow-hidden"
                                value={negativePrompt}
                                onChange={(e) => {
                                    setNegativePrompt(e.target.value);
                                    e.target.style.height = 'auto';
                                    e.target.style.height = e.target.scrollHeight + 'px';
                                }}
                                ref={(el) => {
                                    if (el) {
                                        el.style.height = 'auto';
                                        el.style.height = el.scrollHeight + 'px';
                                    }
                                }}
                            />
                        </div>
                    </div>

                    {/* Model Selection */}
                    <div className="space-y-3 lg:space-y-4 pb-4 border-b border-gray-800">
                        <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2">
                            <Settings2 size={18} className="text-purple-400" />
                            Models
                        </h3>

                        <div className="flex gap-2 items-end">
                            <div className="flex-1">
                                <ModelSelector
                                    label="Checkpoint / UNET"
                                    initialModels={[...checkpoints, ...unetModels]}
                                    value={selectedCheckpoint?.name}
                                    selectedModel={selectedCheckpoint}
                                    onChange={setSelectedCheckpoint}
                                    onVersionChange={setSelectedCheckpoint}
                                    onInfoClick={(model) => setViewingMetadata(model)}
                                />
                            </div>
                        </div>

                        {/* VAE Selector */}
                        <div className="space-y-2">
                            <label className="text-xs font-medium text-gray-500">VAE</label>
                            <select
                                value={selectedVae}
                                onChange={(e) => setSelectedVae(e.target.value)}
                                className="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 text-white text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-all"
                            >
                                <option value="Baked in">Baked in (Default)</option>
                                {vaeModels.map(v => (
                                    <option key={v.name} value={v.name}>{v.name}</option>
                                ))}
                            </select>
                        </div>

                        {/* Flux CLIP Selectors - Only show when Flux model is selected */}
                        {isUnetModel(selectedCheckpoint) && clipModels.length > 0 && (
                            <div className="space-y-3 p-3 bg-gradient-to-r from-purple-900/20 to-blue-900/20 rounded-lg border border-purple-800/30">
                                <div className="flex items-center gap-2">
                                    <Sparkles size={14} className="text-purple-400" />
                                    <label className="text-xs font-medium text-purple-300">
                                        {isFluxModel(selectedCheckpoint) ? "Flux Text Encoders" : "Text Encoder (CLIP)"}
                                    </label>
                                </div>
                                
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                    {/* Primary CLIP (T5XXL for Flux, T5XL/CLIP for AuraFlow) */}
                                    <div className="space-y-1">
                                        <label className="text-[10px] uppercase text-gray-500 font-bold tracking-wider">
                                            {isFluxModel(selectedCheckpoint) ? "T5XXL Encoder" : "Primary Encoder"}
                                        </label>
                                        <select
                                            value={selectedClip || ""}
                                            onChange={(e) => setSelectedClip(e.target.value)}
                                            className="w-full bg-gray-900/80 border border-gray-700/50 rounded px-2 py-1.5 text-xs text-gray-300 focus:border-purple-500 focus:ring-1 focus:ring-purple-500 outline-none"
                                        >
                                            <option value="">Select CLIP...</option>
                                            {clipModels
                                                .filter(m => {
                                                    const n = m.name.toLowerCase();
                                                    // Flux / AuraFlow use T5
                                                    if (isFluxModel(selectedCheckpoint) || isAuraFlowModel(selectedCheckpoint)) {
                                                        return n.includes('t5') || n.includes('fp16') || n.includes('fp8');
                                                    }
                                                    // Pony V7 (SDXL) uses CLIP-G
                                                    if (isPonyModel(selectedCheckpoint)) {
                                                        return n.includes('clip_g') || n.includes('sdxl') || n.includes('vit-g') || (!n.includes('t5') && !n.includes('flux'));
                                                    }
                                                    return true; 
                                                })
                                                .map(m => (
                                                <option key={m.name} value={m.name}>{m.name} ({Math.round(m.size / 1024 / 1024)}MB)</option>
                                            ))}
                                            {/* Show others if not found in filter */}
                                            {clipModels.some(m => !m.name.toLowerCase().includes('t5') && !m.name.toLowerCase().includes('fp16')) && (
                                                <optgroup label="Other">
                                                    {clipModels.filter(m => isFluxModel(selectedCheckpoint) ? (!m.name.toLowerCase().includes('t5') && !m.name.toLowerCase().includes('fp16')) : false).map(m => (
                                                        <option key={m.name} value={m.name}>{m.name}</option>
                                                    ))}
                                                </optgroup>
                                            )}
                                        </select>
                                    </div>

                                    {/* Secondary CLIP (CLIP-L) - FOR FLUX AND PONY (SDXL) */}
                                    {(isFluxModel(selectedCheckpoint) || isPonyModel(selectedCheckpoint)) && (
                                        <div className="space-y-1">
                                            <label className="text-[10px] uppercase text-gray-500 font-bold tracking-wider">CLIP-L Encoder</label>
                                            <select
                                                value={selectedClip2 || ""}
                                                onChange={(e) => setSelectedClip2(e.target.value)}
                                                className="w-full bg-gray-900/80 border border-gray-700/50 rounded px-2 py-1.5 text-xs text-gray-300 focus:border-purple-500 focus:ring-1 focus:ring-purple-500 outline-none"
                                            >
                                                <option value="">Select CLIP...</option>
                                                {clipModels
                                                    .filter(m => m.name.toLowerCase().includes('clip_l') || m.name.toLowerCase().includes('vit-l') || m.name.toLowerCase().includes('sdxl_clip_l'))
                                                    .map(m => (
                                                    <option key={m.name} value={m.name}>{m.name} ({Math.round(m.size / 1024 / 1024)}MB)</option>
                                                ))}
                                            </select>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* Embeddings Quick Select */}
                        {embeddingModels.length > 0 && (
                            <div className="space-y-2">
                                <label className="text-xs font-medium text-gray-500 flex items-center gap-2">
                                    Embeddings
                                    <span className="text-xs text-gray-600">(Click to add to prompt)</span>
                                </label>
                                <div className="flex flex-wrap gap-2">
                                    {embeddingModels.map(emb => {
                                        const isNegative = emb.name.toLowerCase().includes("negative");
                                        const isInPositive = prompt.includes(`embedding:${emb.name}`);
                                        const isInNegative = negativePrompt.includes(`embedding:${emb.name}`);
                                        const isActive = isInPositive || isInNegative;

                                        return (
                                            <button
                                                key={emb.name}
                                                onClick={() => {
                                                    if (isNegative) {
                                                        setNegativePrompt(prev => prev + (prev ? ", " : "") + `embedding:${emb.name}`);
                                                        toast.success(`Added ${emb.name} to Negative Prompt`, { icon: '🚫' });
                                                    } else {
                                                        setPrompt(prev => prev + (prev ? ", " : "") + `embedding:${emb.name}`);
                                                        toast.success(`Added ${emb.name} to Positive Prompt`, { icon: '✨' });
                                                    }
                                                }}
                                                className={`text-xs px-3 py-1.5 rounded-lg border transition-all ${isActive
                                                    ? isNegative
                                                        ? 'bg-red-900/40 border-red-700 text-red-300 ring-1 ring-red-500/50'
                                                        : 'bg-blue-900/40 border-blue-700 text-blue-300 ring-1 ring-blue-500/50'
                                                    : isNegative
                                                        ? 'bg-red-900/20 border-red-800 text-red-400 hover:bg-red-900/40'
                                                        : 'bg-blue-900/20 border-blue-800 text-blue-400 hover:bg-blue-900/40'
                                                    }`}
                                                title={`Click to add to ${isNegative ? "Negative" : "Positive"} Prompt${isActive ? " (Already added)" : ""}`}
                                                type="button"
                                            >
                                                {emb.name}
                                                {isActive && <span className="ml-1">✓</span>}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        )}

                        {/* LoRAs */}
                        <div className="space-y-3">
                            <div className="flex justify-between items-center">
                                <label className="block text-xs font-medium text-gray-500">LoRAs</label>
                                <button onClick={handleAddLora} className="text-xs flex items-center gap-1 text-blue-400 hover:text-blue-300">
                                    <Plus size={14} /> Add LoRA
                                </button>
                            </div>

                            <div className="space-y-2">
                                {selectedLoras.map((lora, idx) => {
                                    // Get all trigger word groups that have at least one unused tag
                                    const activeTriggerGroups = (lora.trained_words || []).map(group => {
                                        const individualTags = group.split(',').map(t => t.trim()).filter(Boolean);
                                        const promptLower = (prompt || '').toLowerCase();
                                        const unusedTags = individualTags.filter(tag => !promptLower.includes(tag.toLowerCase()));

                                        return {
                                            fullGroup: group,
                                            individualTags,
                                            unusedTags,
                                            previewText: group.length > 25 ? group.slice(0, 25) + '…' : group
                                        };
                                    }).filter(g => g.unusedTags.length > 0);
                                    
                                    return (
                                        <div key={idx} className="bg-gray-900/30 rounded-lg border border-gray-700/50 overflow-hidden flex">
                                            {/* Preview image - Left side, filling height */}
                                            {lora.preview ? (
                                                <img 
                                                    src={lora.preview} 
                                                    alt={lora.name}
                                                    className="w-16 h-auto min-h-full object-cover flex-shrink-0 cursor-pointer"
                                                    onClick={() => setAutoOpenLoraIndex(idx)}
                                                    onError={(e) => { e.target.style.display = 'none'; }}
                                                />
                                            ) : (
                                                <div 
                                                    className="w-16 min-h-full bg-gray-800 flex items-center justify-center text-gray-600 flex-shrink-0 cursor-pointer"
                                                    onClick={() => setAutoOpenLoraIndex(idx)}
                                                >
                                                    <ImageIcon size={20} />
                                                </div>
                                            )}
                                            
                                            {/* Right content */}
                                            <div className="flex-1 min-w-0 p-2 space-y-1.5">
                                                {/* Top row: Title + Base model + Info + Delete */}
                                                <div className="flex items-start gap-1">
                                                    {/* Name - clickable, with word wrap */}
                                                    <button
                                                        onClick={() => setAutoOpenLoraIndex(idx)}
                                                        className="flex-1 min-w-0 text-left hover:text-blue-400 transition-colors"
                                                    >
                                                        <div className="text-sm font-medium text-white line-clamp-2 leading-tight">
                                                            {lora.display_name || lora.name || 'Select LoRA...'}
                                                        </div>
                                                        {lora.base_model && (
                                                            <span className="text-[9px] text-gray-500">{lora.base_model}</span>
                                                        )}
                                                    </button>
                                                    
                                                    {/* Info button */}
                                                    <button
                                                        onClick={() => setViewingMetadata(lora)}
                                                        className="p-1 text-gray-500 hover:text-blue-400 transition-colors flex-shrink-0"
                                                        title="View info"
                                                    >
                                                        <Info size={14} />
                                                    </button>
                                                    
                                                    {/* Delete button */}
                                                    <button
                                                        onClick={() => handleRemoveLora(idx)}
                                                        className="p-1 text-gray-500 hover:text-red-400 transition-colors flex-shrink-0"
                                                        title="Remove"
                                                    >
                                                        <Trash2 size={14} />
                                                    </button>
                                                </div>
                                                
                                                {/* Strength row: Slider + Number */}
                                                <div className="flex items-center gap-2">
                                                    <input
                                                        type="range"
                                                        min="-2"
                                                        max="2"
                                                        step="0.1"
                                                        className="flex-1 min-w-0 h-1.5 accent-blue-500"
                                                        value={Math.max(-2, Math.min(2, lora.strength))}
                                                        onChange={(e) => handleLoraChange(idx, 'strength', parseFloat(e.target.value))}
                                                    />
                                                    <input
                                                        type="number"
                                                        step="0.1"
                                                        className="w-12 bg-gray-800 border border-gray-600 rounded px-1.5 py-0.5 text-xs text-white text-center flex-shrink-0"
                                                        value={lora.strength}
                                                        onChange={(e) => handleLoraChange(idx, 'strength', parseFloat(e.target.value) || 0)}
                                                    />
                                                </div>
                                                
                                                {/* Expandable Trigger Word Groups */}
                                                {activeTriggerGroups.length > 0 && (
                                                    <div className="space-y-1 pt-1 border-t border-gray-700/50">
                                                        {activeTriggerGroups.map((group, groupIdx) => {
                                                            const groupKey = `${idx}-${groupIdx}`;
                                                            const isExpanded = expandedTriggerGroups[groupKey];
                                                            
                                                            return (
                                                                <div key={groupIdx} className="space-y-1">
                                                                    {/* Collapsed: Show group header */}
                                                                    <button
                                                                        onClick={() => setExpandedTriggerGroups(prev => ({
                                                                            ...prev,
                                                                            [groupKey]: !isExpanded
                                                                        }))}
                                                                        className="w-full text-left text-[9px] bg-gray-800/50 hover:bg-gray-700/50 text-gray-400 px-1.5 py-1 rounded flex items-center gap-1 transition-colors"
                                                                    >
                                                                        <ChevronDown 
                                                                            size={10} 
                                                                            className={`transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                                                                        />
                                                                        <span className="truncate">{group.previewText}</span>
                                                                        <span className="text-gray-600 flex-shrink-0">({group.individualTags.length})</span>
                                                                    </button>
                                                                    
                                                                    {/* Expanded: Show individual tags */}
                                                                    {isExpanded && (
                                                                        <div className="flex flex-wrap gap-1 pl-2">
                                                                            {/* Add All button */}
                                                                            <button
                                                                                onClick={() => handleAddTriggerWordsUI([group.fullGroup])}
                                                                                className="text-[9px] bg-green-900/30 text-green-300 px-1.5 py-0.5 rounded hover:bg-green-900/50 transition-colors"
                                                                            >
                                                                                + All
                                                                            </button>
                                                                            {/* Individual tags */}
                                                                            {group.unusedTags.map((tag, tagIdx) => (
                                                                                <button
                                                                                    key={tagIdx}
                                                                                    onClick={() => setPrompt(prompt ? `${prompt}, ${tag}` : tag)}
                                                                                    className="text-[9px] bg-blue-900/30 text-blue-300 px-1.5 py-0.5 rounded hover:bg-blue-900/50 transition-colors"
                                                                                >
                                                                                    +{tag}
                                                                                </button>
                                                                            ))}
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            );
                                                        })}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    );
                                })}

                                {/* Hidden ModelSelector for changing LoRAs - only renders when autoOpenLoraIndex is set */}
                                {autoOpenLoraIndex !== null && selectedLoras[autoOpenLoraIndex] && (
                                    <ModelSelector
                                        label="Select LoRA"
                                        value={selectedLoras[autoOpenLoraIndex]?.name}
                                        selectedModel={selectedLoras[autoOpenLoraIndex]}
                                        preview={selectedLoras[autoOpenLoraIndex]?.preview}
                                        metadata={selectedLoras[autoOpenLoraIndex]?.metadata}
                                        onChange={(m) => handleLoraChange(autoOpenLoraIndex, 'model', m)}
                                        onInfoClick={(model) => setViewingMetadata(model)}
                                        directory="models/loras"
                                        autoOpen={true}
                                        onAutoOpenComplete={() => setAutoOpenLoraIndex(null)}
                                    />
                                )}
                            </div>
                        </div>
                    </div>

                    {/* ControlNet - Collapsible, open if has controlnets */}
                    <CollapsibleSection 
                        title="ControlNet" 
                        icon={<Settings2 size={20} className="text-green-400" />}
                        defaultOpen={controlnets.length > 0}
                    >
                        <div className="space-y-4">
                            <div className="flex justify-end">
                                <button onClick={handleAddControlNet} className="text-xs flex items-center gap-1 text-blue-400 hover:text-blue-300">
                                    <Plus size={14} /> Add ControlNet
                                </button>
                            </div>

                        {controlnets.map((cn, idx) => (
                            <div key={idx} className="space-y-3 bg-gray-900/50 p-4 rounded-lg border border-gray-700 relative">
                                <button onClick={() => handleRemoveControlNet(idx)} className="absolute top-2 right-2 text-gray-500 hover:text-red-400">
                                    <Trash2 size={16} />
                                </button>

                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                    <div>
                                        <label className="block text-xs font-medium text-gray-500 mb-1">Model</label>
                                        <select
                                            className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-sm text-white"
                                            value={cn.name}
                                            onChange={(e) => handleControlNetChange(idx, 'name', e.target.value)}
                                        >
                                            <option value="">Select Model...</option>
                                            {controlNetModels.map(m => (
                                                <option key={m.name} value={m.name}>{m.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-xs font-medium text-gray-500 mb-1">Strength</label>
                                        <input
                                            type="number"
                                            step="0.1"
                                            className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-sm text-white"
                                            value={cn.strength}
                                            onChange={(e) => handleControlNetChange(idx, 'strength', parseFloat(e.target.value))}
                                        />
                                    </div>
                                </div>

                                <div>
                                    <label className="block text-xs font-medium text-gray-500 mb-1">Input Image</label>
                                    <div className="flex gap-2 items-center">
                                        <input
                                            type="file"
                                            className="text-sm text-gray-400"
                                            onChange={(e) => e.target.files?.[0] && handleControlNetUpload(idx, e.target.files[0])}
                                        />
                                        {cn.image && <span className="text-xs text-green-400">Uploaded: {cn.image}</span>}
                                    </div>
                                </div>

                                <div>
                                    <label className="block text-xs font-medium text-gray-500 mb-1">Preprocessor</label>
                                    <select
                                        className="w-full bg-gray-800 border border-gray-600 rounded p-2 text-sm text-white"
                                        value={cn.preprocessor}
                                        onChange={(e) => handleControlNetChange(idx, 'preprocessor', e.target.value)}
                                    >
                                        <option value="None">None (Raw Image)</option>
                                        <option value="Canny">Canny Edge</option>
                                    </select>
                                </div>
                            </div>
                        ))}
                        </div>
                    </CollapsibleSection>

                    {/* Enhancements - Collapsible, open if either feature is enabled */}
                    <CollapsibleSection 
                        title="Enhancements" 
                        icon={<Sparkles size={20} className="text-yellow-400" />}
                        defaultOpen={hiresFix || adetailer}
                    >
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            {/* Hi-Res Fix */}
                            <div className="space-y-4">
                                <div className="flex items-center gap-2">
                                    <input
                                        type="checkbox"
                                        checked={hiresFix}
                                        onChange={(e) => setHiresFix(e.target.checked)}
                                        className="rounded bg-gray-700 border-gray-600 w-4 h-4 text-blue-600 focus:ring-blue-500"
                                        id="hiresFix"
                                    />
                                    <label htmlFor="hiresFix" className="text-sm font-medium text-white cursor-pointer select-none">Hi-Res Fix</label>
                                </div>

                                <div className={`space-y-3 pl-6 border-l-2 border-gray-700 ml-2 transition-all ${hiresFix ? 'opacity-100' : 'opacity-50 pointer-events-none'}`}>
                                    <div>
                                        <label className="block text-xs text-gray-500 mb-1">Upscaler</label>
                                        <select
                                            value={hiresUpscaler}
                                            onChange={(e) => setHiresUpscaler(e.target.value)}
                                            className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                                        >
                                            <option value="Latent">Latent (Default)</option>
                                            {upscalerModels.map(m => (
                                                <option key={m.name} value={m.name}>{m.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                        <div>
                                            <label className="block text-xs text-gray-500 mb-1">Scale</label>
                                            <input
                                                type="number"
                                                step="0.1"
                                                value={hiresUpscale}
                                                onChange={(e) => setHiresUpscale(parseFloat(e.target.value))}
                                                className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                                            />
                                        </div>
                                        <div>
                                            <label className="block text-xs text-gray-500 mb-1">Denoise</label>
                                            <input
                                                type="number"
                                                step="0.05"
                                                value={hiresDenoise}
                                                onChange={(e) => setHiresDenoise(parseFloat(e.target.value))}
                                                className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                                            />
                                        </div>
                                    </div>
                                    <div>
                                        <label className="block text-xs text-gray-500 mb-1">Steps</label>
                                        <input
                                            type="number"
                                            value={hiresSteps}
                                            onChange={(e) => setHiresSteps(parseInt(e.target.value))}
                                            className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                                        />
                                    </div>
                                </div>
                            </div>

                            {/* ADetailer */}
                            <div className="space-y-4">
                                <div className="flex items-center gap-2">
                                    <input
                                        type="checkbox"
                                        checked={adetailer}
                                        onChange={(e) => setAdetailer(e.target.checked)}
                                        className="rounded bg-gray-700 border-gray-600 w-4 h-4 text-blue-600 focus:ring-blue-500"
                                        id="adetailer"
                                    />
                                    <label htmlFor="adetailer" className="text-sm font-medium text-white cursor-pointer select-none">ADetailer</label>
                                </div>

                                <div className={`space-y-3 pl-6 border-l-2 border-gray-700 ml-2 transition-all ${adetailer ? 'opacity-100' : 'opacity-50 pointer-events-none'}`}>
                                    <div>
                                        <label className="block text-xs text-gray-500 mb-1">Model</label>
                                        <select
                                            value={adetailerModel}
                                            onChange={(e) => setAdetailerModel(e.target.value)}
                                            className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                                        >
                                            {adetailerModels.map(m => (
                                                <option key={m.name} value={m.name}>{m.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-xs text-gray-500 mb-1">Prompt (Optional)</label>
                                        <input
                                            type="text"
                                            value={adetailerPrompt}
                                            onChange={(e) => setAdetailerPrompt(e.target.value)}
                                            placeholder="e.g. detailed face, blue eyes"
                                            className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                                        />
                                    </div>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                        <div>
                                            <label className="block text-xs text-gray-500 mb-1">Steps</label>
                                            <input
                                                type="number"
                                                value={adetailerSteps}
                                                onChange={(e) => setAdetailerSteps(parseInt(e.target.value))}
                                                className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                                            />
                                        </div>
                                        <div>
                                            <label className="block text-xs text-gray-500 mb-1">Denoise</label>
                                            <input
                                                type="number"
                                                step="0.05"
                                                value={adetailerDenoise}
                                                onChange={(e) => setAdetailerDenoise(parseFloat(e.target.value))}
                                                className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                                            />
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <input
                                            type="checkbox"
                                            checked={adetailerInpaintMasked}
                                            onChange={(e) => setAdetailerInpaintMasked(e.target.checked)}
                                            className="rounded bg-gray-700 border-gray-600"
                                            id="inpaintMasked"
                                        />
                                        <label htmlFor="inpaintMasked" className="text-xs text-gray-400 select-none cursor-pointer">Inpaint Masked Only</label>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </CollapsibleSection>
                </div>

                {/* Right Column: Parameters - ORDER FIRST on mobile for easy access */}
                <div className="order-first lg:order-none space-y-4 lg:space-y-6">
                    <div className="space-y-4 lg:space-y-6 pb-4 border-b border-gray-800 lg:border-0">
                        <div className="flex justify-between items-center">
                            <h3 className="text-base lg:text-lg font-semibold">Parameters</h3>
                            <PresetManager />
                        </div>

                        <div className="space-y-3 lg:space-y-4">
                            <label className="text-xs font-medium text-gray-500 uppercase tracking-wider">Resolution</label>
                            
                            <div className="grid grid-cols-4 gap-1.5">
                                {[
                                    { w: 1024, h: 1024, label: "1:1" },
                                    { w: 832, h: 1216, label: "2:3" },
                                    { w: 1216, h: 832, label: "3:2" },
                                    { w: 896, h: 1152, label: "3:4" },
                                    { w: 1152, h: 896, label: "4:3" },
                                    { w: 1344, h: 768, label: "16:9" },
                                    { w: 768, h: 1344, label: "9:16" },
                                    { w: 1536, h: 640, label: "21:9" },
                                ].map((p) => (
                                    <button
                                        key={p.label}
                                        onClick={() => setResolution(p.w, p.h)}
                                        aria-label={`Set aspect ratio ${p.label}, ${p.w}x${p.h} pixels`}
                                        title={`Set aspect ratio ${p.label} (${p.w}x${p.h})`}
                                        aria-pressed={width === p.w && height === p.h}
                                        className={`flex flex-col items-center justify-center gap-0.5 p-1.5 rounded-lg transition-all border focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none ${width === p.w && height === p.h ? 'bg-blue-600/20 border-blue-500 text-blue-400' : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700 hover:text-gray-300'}`}
                                    >
                                        <div className="w-5 h-5 flex items-center justify-center">
                                            <div
                                                className="border-2 border-current rounded-sm transition-all"
                                                style={{
                                                    width: p.w >= p.h ? '14px' : `${(p.w / p.h) * 14}px`,
                                                    height: p.h >= p.w ? '14px' : `${(p.h / p.w) * 14}px`
                                                }}
                                            />
                                        </div>
                                        <span className="text-[10px] font-bold">{p.label}</span>
                                    </button>
                                ))}
                            </div>

                            {/* Width - Lock - Height row */}
                            <div className="flex items-end gap-2">
                                <div className="flex-1">
                                    <label htmlFor="width-input" className="block text-xs font-medium text-gray-500 mb-1">Width</label>
                                    <input
                                        id="width-input"
                                        type="number"
                                        value={width}
                                        onChange={(e) => handleDimensionChange('width', e.target.value)}
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-white text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                                    />
                                </div>
                                <button
                                    onClick={() => setAspectRatioLocked(!aspectRatioLocked)}
                                    className={`no-touch-padding px-2.5 py-1.5 rounded-lg border transition-colors flex items-center justify-center ${aspectRatioLocked ? 'bg-blue-600 text-white border-blue-500' : 'bg-gray-800 text-gray-400 hover:text-white border-gray-700'}`}
                                    title={aspectRatioLocked ? "Unlock Aspect Ratio" : "Lock Aspect Ratio"}
                                    aria-label={aspectRatioLocked ? "Unlock Aspect Ratio" : "Lock Aspect Ratio"}
                                    aria-pressed={aspectRatioLocked}
                                >
                                    {aspectRatioLocked ? <Lock size={16} /> : <Unlock size={16} />}
                                </button>
                                <div className="flex-1">
                                    <label htmlFor="height-input" className="block text-xs font-medium text-gray-500 mb-1">Height</label>
                                    <input
                                        id="height-input"
                                        type="number"
                                        value={height}
                                        onChange={(e) => handleDimensionChange('height', e.target.value)}
                                        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-white text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                                    />
                                </div>
                            </div>
                        </div>

                        {/* Batch Size */}
                        <NumberInput
                            label="Batch Size"
                            value={batchSize}
                            onChange={(val) => setBatchSize(Math.max(1, Math.min(16, val)))}
                            min={1}
                            max={16}
                        />

                        {/* Steps & CFG - Compact with sliders */}
                        <div className="grid grid-cols-2 gap-2">
                            <NumberInput
                                label="Steps"
                                value={steps}
                                onChange={(val) => setSteps(Math.max(1, val))}
                                min={1}
                                max={100}
                            />
                            <NumberInput
                                label="CFG"
                                value={cfg}
                                onChange={(val) => setCfg(Math.max(0, val))}
                                min={1}
                                max={30}
                                step={0.5}
                            />
                        </div>

                        {/* Seed - Compact inline layout */}
                        <div className="space-y-1">
                            <label className="text-xs font-medium text-gray-500">Seed</label>
                            <div className="flex gap-1.5 items-stretch">
                                <input
                                    type="number"
                                    value={seed}
                                    onChange={(e) => setSeed(parseInt(e.target.value))}
                                    className="flex-1 min-w-0 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white font-mono"
                                />
                                <button
                                    onClick={() => {
                                        setSeed(Math.floor(Math.random() * Number.MAX_SAFE_INTEGER));
                                        if (!autoRandomizeSeed) {
                                            updateSetting('generator', 'autoRandomizeSeed', true);
                                            toast.success('Auto-randomize enabled!', { icon: '🎲', duration: 2000 });
                                        }
                                    }}
                                    className="no-touch-padding w-10 flex items-center justify-center bg-gray-700 hover:bg-gray-600 border border-gray-600 rounded transition-colors flex-shrink-0 text-base"
                                    title="Randomize seed"
                                >
                                    🎲
                                </button>
                                <button
                                    onClick={() => updateSetting('generator', 'autoRandomizeSeed', !autoRandomizeSeed)}
                                    className={`no-touch-padding w-10 flex items-center justify-center border rounded transition-colors flex-shrink-0 ${
                                        autoRandomizeSeed 
                                            ? 'bg-blue-600 text-white border-blue-500' 
                                            : 'bg-gray-700 text-gray-400 hover:bg-gray-600 border-gray-600'
                                    }`}
                                    title={autoRandomizeSeed ? 'Auto-randomize ON' : 'Auto-randomize OFF'}
                                >
                                    <RefreshCw size={16} />
                                </button>
                            </div>
                        </div>

                        {/* Sampler & Scheduler */}
                        <div className="grid grid-cols-2 gap-2">
                            <div>
                                <label className="block text-xs font-medium text-gray-500 mb-1">Sampler</label>
                                <select 
                                    value={sampler} 
                                    onChange={(e) => setSampler(e.target.value)} 
                                    className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
                                >
                                    <option value="euler">Euler</option>
                                    <option value="euler_ancestral">Euler a</option>
                                    <option value="heun">Heun</option>
                                    <option value="heunpp2">Heun++ 2</option>
                                    <option value="dpm_2">DPM 2</option>
                                    <option value="dpm_2_ancestral">DPM 2 a</option>
                                    <option value="lms">LMS</option>
                                    <option value="dpm_fast">DPM Fast</option>
                                    <option value="dpm_adaptive">DPM Adaptive</option>
                                    <option value="dpmpp_2s_ancestral">DPM++ 2S a</option>
                                    <option value="dpmpp_sde">DPM++ SDE</option>
                                    <option value="dpmpp_sde_gpu">DPM++ SDE GPU</option>
                                    <option value="dpmpp_2m">DPM++ 2M</option>
                                    <option value="dpmpp_2m_sde">DPM++ 2M SDE</option>
                                    <option value="dpmpp_2m_sde_gpu">DPM++ 2M SDE GPU</option>
                                    <option value="dpmpp_3m_sde">DPM++ 3M SDE</option>
                                    <option value="dpmpp_3m_sde_gpu">DPM++ 3M SDE GPU</option>
                                    <option value="ddpm">DDPM</option>
                                    <option value="lcm">LCM</option>
                                    <option value="ddim">DDIM</option>
                                    <option value="uni_pc">UniPC</option>
                                    <option value="uni_pc_bh2">UniPC BH2</option>
                                </select>
                            </div>

                            <div>
                                <label className="block text-xs font-medium text-gray-500 mb-1">Scheduler</label>
                                <select 
                                    value={scheduler} 
                                    onChange={(e) => setScheduler(e.target.value)} 
                                    className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
                                >
                                    <option value="normal">Normal</option>
                                    <option value="karras">Karras</option>
                                    <option value="exponential">Exponential</option>
                                    <option value="sgm_uniform">SGM Uniform</option>
                                    <option value="simple">Simple</option>
                                    <option value="ddim_uniform">DDIM Uniform</option>
                                </select>
                            </div>
                        </div>
                    </div>

                    {/* Generate Button Bar - Desktop only (inline in Parameters section) */}
                    <div className="hidden md:block">
                        <div className="flex gap-2">
                            <button
                                onClick={() => handleGenerate(false)}
                                disabled={generating || !prompt}
                                className={`flex-1 h-12 rounded-xl font-bold text-base shadow-lg transition-all transform active:scale-95 border border-gray-700 flex items-center justify-center ${generating
                                    ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
                                    : 'bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white'
                                    }`}
                            >
                                <Plus size={18} />
                            </button>

                            {/* Variations Dropdown */}
                            <div className="relative">
                                <button
                                    onClick={() => setShowVariationsMenu(!showVariationsMenu)}
                                    disabled={generating || !prompt}
                                    className={`h-12 px-4 rounded-xl font-bold text-base shadow-lg transition-all transform active:scale-95 border flex items-center justify-center ${generating || !prompt
                                        ? 'bg-gray-800 text-gray-500 cursor-not-allowed border-gray-700'
                                        : 'bg-purple-900/50 hover:bg-purple-800/50 text-purple-300 hover:text-purple-200 border-purple-700'
                                        }`}
                                    title="Generate Variations"
                                >
                                    <Layers size={18} />
                                </button>

                                {/* Dropdown Menu */}
                                {showVariationsMenu && (
                                    <div className="absolute bottom-full mb-2 right-0 bg-gray-800 border border-gray-700 rounded-xl shadow-xl py-2 min-w-[160px] z-50">
                                        <div className="px-3 py-1 text-xs text-gray-500 uppercase tracking-wider">Seed Variations</div>
                                        {[2, 4, 8].map(count => (
                                            <button
                                                key={count}
                                                onClick={() => handleGenerateVariations(count)}
                                                className="w-full px-4 py-2 text-left text-sm text-gray-300 hover:bg-purple-900/30 hover:text-purple-300 transition-colors"
                                            >
                                                Generate {count}x
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </div>

                            <button
                                onClick={() => handleGenerate(true)}
                                disabled={generating || !prompt}
                                className={`flex-[3] h-12 rounded-xl font-bold text-base shadow-lg transition-all transform active:scale-95 flex items-center justify-center ${generating
                                    ? 'bg-gray-700 text-gray-400 cursor-not-allowed'
                                    : 'bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white shadow-blue-900/20'
                                    }`}
                            >
                                {generating ? (
                                    <span className="flex items-center justify-center gap-2">
                                        <Loader2 className="animate-spin" size={20} />
                                        Generating...
                                    </span>
                                ) : (
                                    "Generate"
                                )}
                            </button>
                        </div>
                        {/* Visual Progress Bar */}
                        {generating && progress && (
                            <div className="absolute top-0 left-0 h-1 bg-gradient-to-r from-blue-500 to-purple-500 transition-all duration-300 ease-out" style={{ width: `${progress.value}%` }} />
                        )}
                        {generating && progress && progress.node && (
                            <div className="text-center text-[10px] text-gray-400 mt-1">
                                {progress.node}
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Spacer for mobile to prevent content being hidden behind fixed button */}
            <div className="h-20 md:hidden"></div>

            {/* Generate Button Bar - Fixed at bottom on mobile */}
            <div className="fixed bottom-0 left-0 right-0 p-3 bg-gray-900/95 backdrop-blur-xl border-t border-gray-800 md:hidden z-30 pb-safe">
                <div className="flex gap-2">
                    <button
                        onClick={() => handleGenerate(false)}
                        disabled={generating || !prompt}
                        className={`flex-1 h-12 rounded-xl font-bold text-base shadow-lg transition-all transform active:scale-95 border border-gray-700 flex items-center justify-center ${generating
                            ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
                            : 'bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white'
                            }`}
                    >
                        <Plus size={18} />
                    </button>

                    {/* Variations Dropdown */}
                    <div className="relative">
                        <button
                            onClick={() => setShowVariationsMenu(!showVariationsMenu)}
                            disabled={generating || !prompt}
                            className={`h-12 px-4 rounded-xl font-bold text-base shadow-lg transition-all transform active:scale-95 border flex items-center justify-center ${generating || !prompt
                                ? 'bg-gray-800 text-gray-500 cursor-not-allowed border-gray-700'
                                : 'bg-purple-900/50 hover:bg-purple-800/50 text-purple-300 hover:text-purple-200 border-purple-700'
                                }`}
                            title="Generate Variations"
                        >
                            <Layers size={18} />
                        </button>

                        {/* Dropdown Menu */}
                        {showVariationsMenu && (
                            <div className="absolute bottom-full mb-2 right-0 bg-gray-800 border border-gray-700 rounded-xl shadow-xl py-2 min-w-[160px] z-50">
                                <div className="px-3 py-1 text-xs text-gray-500 uppercase tracking-wider">Seed Variations</div>
                                {[2, 4, 8].map(count => (
                                    <button
                                        key={count}
                                        onClick={() => handleGenerateVariations(count)}
                                        className="w-full px-4 py-2 text-left text-sm text-gray-300 hover:bg-purple-900/30 hover:text-purple-300 transition-colors"
                                    >
                                        Generate {count}x
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    <button
                        onClick={() => handleGenerate(true)}
                        disabled={generating || !prompt}
                        className={`flex-[3] h-12 rounded-xl font-bold text-base shadow-lg transition-all transform active:scale-95 flex items-center justify-center ${generating
                            ? 'bg-gray-700 text-gray-400 cursor-not-allowed'
                            : 'bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white shadow-blue-900/20'
                            }`}
                    >
                        {generating ? (
                            <span className="flex items-center justify-center gap-2">
                                <Loader2 className="animate-spin" size={20} />
                                Generating...
                            </span>
                        ) : (
                            "Generate"
                        )}
                    </button>
                </div>
                {/* Visual Progress Bar */}
                {generating && progress && (
                    <div className="absolute top-0 left-0 h-1 bg-gradient-to-r from-blue-500 to-purple-500 transition-all duration-300 ease-out" style={{ width: `${progress.value}%` }} />
                )}
                {generating && progress && progress.node && (
                    <div className="text-center text-[10px] text-gray-400 mt-1">
                        {progress.node}
                    </div>
                )}
            </div>

            {viewingMetadata && (
                <ModelMetadataModal
                    metadata={viewingMetadata}
                    onClose={() => setViewingMetadata(null)}
                />
            )}

            {/* Prompt Library Modal */}
            <PromptLibrary
                isOpen={showPromptLibrary}
                onClose={() => setShowPromptLibrary(false)}
                onSelectPrompt={handleSelectPromptFromLibrary}
            />

            {/* Quick Nav to Gallery (Mobile) */}
            <button
                onClick={() => navigate('/')}
                className="fixed bottom-6 right-6 z-40 md:hidden bg-purple-600 hover:bg-purple-500 text-white p-4 rounded-full shadow-lg transition-all transform hover:scale-110 flex items-center gap-2"
                title="Go to Gallery"
            >
                <FolderOpen size={24} />
            </button>
        </div>
    );
}
