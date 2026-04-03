/**
 * Inpainting Generator Page
 * 
 * Dedicated page for inpainting - regenerating masked areas of an image.
 * Uses a Fabric.js canvas for mask drawing.
 */

import { useState, useEffect, useMemo } from 'react';
import { Paintbrush, Wand2, Settings2, Play, Trash2, Plus, Loader2, ArrowLeft, RefreshCw, Sparkles } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useModelDirectories } from '../hooks/useModelDirectories';
import toast from 'react-hot-toast';

import { WorkflowBuilder } from '../utils/workflowBuilder';
import { useGeneratorStore } from '../store/generatorStore';
import { useJobStore } from '../store/jobStore';
import { filesApi, generateApi, createIdempotencyKey } from '../api';
import { getApiUrl } from '../api/config';
import ImageUploader from '../components/generator/ImageUploader';
import InpaintCanvas from '../components/generator/InpaintCanvas';
import ModelSelector from '../components/ModelSelector';
import { useSettings } from '../store/settingsStore';
import GeneratorTabs from '../components/generator/GeneratorTabs';

const EMPTY_MODELS = [];

export default function InpaintGenerator() {
    const navigate = useNavigate();
    const location = useLocation();
    const settings = useSettings();
    const [generating, setGenerating] = useState(false);
    const [autoOpenLoraIndex, setAutoOpenLoraIndex] = useState(null);
    const [showCanvas, setShowCanvas] = useState(false);

    // Global State from Store
    const {
        prompt, negativePrompt, seed, steps, cfg, sampler, scheduler,
        sourceImage, denoise, maskImage, maskBlur,
        selectedCheckpoint, selectedVae, selectedLoras,
        setPrompt, setNegativePrompt, setSeed, setSteps, setCfg, setSampler, setScheduler,
        setSourceImage, setDenoise, setMaskImage, setMaskBlur, clearSourceImage,
        setSelectedCheckpoint, setSelectedVae,
        randomizeSeed, addLora, removeLora, updateLora
    } = useGeneratorStore();

    const activeJobCount = useJobStore(state => state.jobs.filter(j => j.status === 'pending' || j.status === 'running').length);
    const modelRequests = useMemo(() => ([
        { key: 'checkpoints', directory: 'models/checkpoints', label: 'checkpoints' },
        { key: 'vaeModels', directory: 'models/vae', label: 'VAE models' },
    ]), []);
    const { modelsByKey } = useModelDirectories(modelRequests);
    const checkpoints = modelsByKey.checkpoints ?? EMPTY_MODELS;
    const vaeModels = modelsByKey.vaeModels ?? EMPTY_MODELS;

    // Check for pre-loaded image from navigation state
    useEffect(() => {
        if (location.state?.sourceImage) {
            setSourceImage(location.state.sourceImage);
            setShowCanvas(true);
        }
    }, [location.state, setSourceImage]);

    // Auto-detect inpaint model if available
    const inpaintCheckpoint = useMemo(() => {
        if (!selectedCheckpoint) return null;

        // Look for inpainting version of current model
        const baseName = selectedCheckpoint.name?.replace(/\.(safetensors|ckpt)$/, '') || '';
        const inpaintVariant = checkpoints.find(m => {
            const name = m.name?.toLowerCase() || '';
            return name.includes('inpaint') && (
                name.includes(baseName.toLowerCase()) ||
                baseName.toLowerCase().includes(name.replace('inpaint', '').replace(/-/g, '').trim())
            );
        });

        return inpaintVariant || null;
    }, [selectedCheckpoint, checkpoints]);

    // When source image is loaded, show canvas
    useEffect(() => {
        if (sourceImage?.filename && !showCanvas) {
            setShowCanvas(true);
        }
    }, [sourceImage, showCanvas]);

    const handleGenerate = async () => {
        if (!sourceImage?.filename) {
            toast.error("Please upload a source image first");
            return;
        }

        if (!maskImage) {
            toast.error("Please draw a mask on the image");
            return;
        }

        if (!selectedCheckpoint?.name) {
            toast.error("Please select a checkpoint");
            return;
        }

        setGenerating(true);

        try {
            // Use inpaint model if detected, otherwise use selected
            const checkpointToUse = inpaintCheckpoint?.name || selectedCheckpoint.name;

            // First, upload the mask to the backend
            const maskResult = await filesApi.uploadMask(
                maskImage,
                sourceImage.filename,
            );

            const builder = new WorkflowBuilder();
            const workflow = builder.buildInpaint({
                inputImage: sourceImage.filename,
                maskImage: maskResult.filename,
                prompt,
                negativePrompt,
                seed,
                steps,
                cfg,
                sampler,
                scheduler,
                denoise,
                checkpoint: checkpointToUse,
                loras: selectedLoras,
                vae: selectedVae,
                maskBlur,
                growMask: 6
            });

            const metadata = {
                type: 'inpaint',
                prompt,
                negativePrompt,
                seed,
                steps,
                cfg,
                sampler,
                scheduler,
                denoise,
                maskBlur,
                width: sourceImage.width,
                height: sourceImage.height,
                sourceImage: sourceImage.filename,
                maskImage: maskResult.filename,
                checkpoint: inpaintCheckpoint || selectedCheckpoint,
                vae: selectedVae,
                loras: selectedLoras,
                usedInpaintModel: !!inpaintCheckpoint
            };

            await generateApi.workflow(workflow, metadata, {
                idempotencyKey: createIdempotencyKey('generate-inpaint')
            });

            if (settings.generator.redirectAfterGenerate) {
                toast.success('Job queued! Redirecting to gallery...');
                setTimeout(() => navigate('/'), settings.generator.redirectDelay);
            } else {
                toast.success('Job added to queue!');
                if (settings.generator.autoRandomizeSeed) {
                    setSeed(Math.floor(Math.random() * Number.MAX_SAFE_INTEGER));
                }
            }

        } catch (e) {
            console.error(e);
            toast.error("Error: " + e.message);
        } finally {
            setGenerating(false);
        }
    };

    const handleClearAll = () => {
        clearSourceImage();
        setShowCanvas(false);
    };

    // Sampler options
    const samplers = ['euler', 'euler_ancestral', 'dpmpp_2m', 'dpmpp_sde', 'ddim', 'uni_pc'];
    const schedulers = ['normal', 'karras', 'exponential', 'sgm_uniform'];

    return (
        <div className="pb-24">
            {/* Header with Tabs */}
            <div className="max-w-6xl mx-auto mb-6">
                <div className="flex justify-between items-center mb-4">
                    <h1 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-pink-500">
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

            <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-4 lg:gap-8">
                {/* Left Column: Canvas & Settings */}
                <div className="lg:col-span-2 space-y-4 lg:space-y-6">

                    {/* Source Image / Canvas */}
                    <div className="space-y-3 pb-4 border-b border-gray-800">
                        <div className="flex justify-between items-center">
                            <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2">
                                <Paintbrush size={18} className="text-purple-400" />
                                {showCanvas ? 'Draw Mask' : 'Source Image'}
                            </h3>
                            {sourceImage && (
                                <button
                                    onClick={handleClearAll}
                                    className="text-xs text-red-400 hover:text-red-300 flex items-center gap-1"
                                >
                                    <Trash2 size={14} /> Clear
                                </button>
                            )}
                        </div>

                        {!sourceImage ? (
                            <ImageUploader
                                image={sourceImage}
                                onImageSelect={(img) => {
                                    setSourceImage(img);
                                    setShowCanvas(true);
                                }}
                                onClear={handleClearAll}
                            />
                        ) : (
                            <InpaintCanvas
                                sourceImageUrl={sourceImage.previewUrl || `${getApiUrl()}${sourceImage.localPreview}`}
                                sourceWidth={sourceImage.width}
                                sourceHeight={sourceImage.height}
                                onMaskChange={setMaskImage}
                            />
                        )}

                        {sourceImage && (
                            <p className="text-xs text-gray-500 text-center">
                                Paint over areas you want to regenerate • White = regenerate, Black = keep
                            </p>
                        )}
                    </div>

                    {/* Prompt Section */}
                    <div className="space-y-3 pb-4 border-b border-gray-800">
                        <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2">
                            <Wand2 size={18} className="text-blue-400" />
                            Prompts
                        </h3>
                        <div>
                            <label className="block text-sm font-medium text-gray-400 mb-1">
                                What to generate (in masked area)
                            </label>
                            <textarea
                                className="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 text-white min-h-[6rem] focus:ring-2 focus:ring-blue-500 outline-none resize-y"
                                value={prompt}
                                onChange={(e) => setPrompt(e.target.value)}
                                placeholder="Describe what you want in the masked area..."
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-gray-400 mb-1">Negative Prompt</label>
                            <textarea
                                className="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 text-white min-h-[4rem] focus:ring-2 focus:ring-red-500 outline-none resize-y"
                                value={negativePrompt}
                                onChange={(e) => setNegativePrompt(e.target.value)}
                                placeholder="What to avoid..."
                            />
                        </div>
                    </div>

                    {/* Model Selection */}
                    <div className="space-y-4 pb-4 border-b border-gray-800">
                        <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2">
                            <Settings2 size={18} className="text-purple-400" />
                            Models
                        </h3>

                        <ModelSelector
                            label="Checkpoint"
                            initialModels={checkpoints}
                            value={selectedCheckpoint?.name}
                            selectedModel={selectedCheckpoint}
                            onChange={setSelectedCheckpoint}
                            directory="models/checkpoints"
                        />

                        {/* Inpaint Model Detection */}
                        {inpaintCheckpoint && (
                            <div className="bg-purple-900/20 border border-purple-700/50 rounded-lg p-3 flex items-center gap-3">
                                <Sparkles size={18} className="text-purple-400" />
                                <div>
                                    <p className="text-sm text-purple-300 font-medium">
                                        Inpaint model detected!
                                    </p>
                                    <p className="text-xs text-gray-400">
                                        Using: {inpaintCheckpoint.display_name || inpaintCheckpoint.name}
                                    </p>
                                </div>
                            </div>
                        )}

                        {/* VAE Selector */}
                        <div className="space-y-2">
                            <label className="text-xs font-medium text-gray-500">VAE</label>
                            <select
                                value={selectedVae}
                                onChange={(e) => setSelectedVae(e.target.value)}
                                className="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 text-white text-sm"
                            >
                                <option value="Baked in">Baked in (Default)</option>
                                {vaeModels.map(v => (
                                    <option key={v.name} value={v.name}>{v.name}</option>
                                ))}
                            </select>
                        </div>

                        {/* LoRAs */}
                        <div className="space-y-3">
                            <div className="flex justify-between items-center">
                                <label className="block text-xs font-medium text-gray-500">LoRAs</label>
                                <button
                                    onClick={() => {
                                        addLora();
                                        setAutoOpenLoraIndex(selectedLoras.length);
                                    }}
                                    className="text-xs flex items-center gap-1 text-blue-400 hover:text-blue-300"
                                >
                                    <Plus size={14} /> Add LoRA
                                </button>
                            </div>

                            {selectedLoras.map((lora, idx) => (
                                <div key={idx} className="bg-gray-900/50 p-3 rounded-lg border border-gray-700 space-y-2">
                                    <ModelSelector
                                        label={`LoRA ${idx + 1}`}
                                        value={lora.name}
                                        selectedModel={lora}
                                        onChange={(m) => updateLora(idx, 'model', m)}
                                        directory="models/loras"
                                        autoOpen={autoOpenLoraIndex === idx}
                                        onAutoOpenComplete={() => setAutoOpenLoraIndex(null)}
                                    />
                                    <div className="flex gap-2 items-center">
                                        <div className="flex-1">
                                            <label className="text-xs text-gray-500">Strength</label>
                                            <div className="flex gap-2 items-center">
                                                <input
                                                    type="range"
                                                    min="-4"
                                                    max="4"
                                                    step="0.1"
                                                    className="flex-1"
                                                    value={lora.strength}
                                                    onChange={(e) => updateLora(idx, 'strength', parseFloat(e.target.value))}
                                                />
                                                <input
                                                    type="number"
                                                    step="0.1"
                                                    className="w-16 bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs text-white text-center"
                                                    value={lora.strength}
                                                    onChange={(e) => updateLora(idx, 'strength', parseFloat(e.target.value))}
                                                />
                                            </div>
                                        </div>
                                        <button
                                            onClick={() => removeLora(idx)}
                                            className="text-red-400 hover:text-red-300 p-2 bg-gray-800 rounded-lg self-end"
                                            title="Remove LoRA"
                                        >
                                            <Trash2 size={16} />
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

                {/* Right Column: Parameters */}
                <div className="space-y-4 lg:space-y-6">
                    {/* Denoise Strength */}
                    <div className="space-y-3 pb-4 border-b border-gray-800">
                        <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2 text-purple-400">
                            <Paintbrush size={18} />
                            Inpaint Strength
                        </h3>
                        <div className="space-y-2">
                            <input
                                type="range"
                                min="0"
                                max="1"
                                step="0.05"
                                value={denoise}
                                onChange={(e) => setDenoise(parseFloat(e.target.value))}
                                className="w-full accent-purple-500"
                            />
                            <div className="text-center">
                                <span className="text-2xl font-bold text-purple-400">{denoise.toFixed(2)}</span>
                            </div>
                            <p className="text-xs text-gray-500 text-center">
                                Higher = more creative • 0.8-1.0 recommended for inpainting
                            </p>
                        </div>
                    </div>

                    {/* Mask Blur */}
                    <div className="space-y-3 pb-4 border-b border-gray-800">
                        <h3 className="text-sm font-medium text-gray-300">Mask Blur</h3>
                        <div className="flex items-center gap-4">
                            <input
                                type="range"
                                min="0"
                                max="20"
                                value={maskBlur}
                                onChange={(e) => setMaskBlur(parseInt(e.target.value))}
                                className="flex-1"
                            />
                            <span className="text-sm text-white w-12">{maskBlur}px</span>
                        </div>
                        <p className="text-xs text-gray-500">
                            Blur mask edges for smoother blending
                        </p>
                    </div>

                    {/* Sampling Parameters */}
                    <div className="space-y-3 pb-4 border-b border-gray-800">
                        <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2">
                            <Settings2 size={18} className="text-gray-400" />
                            Sampling
                        </h3>

                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-xs font-medium text-gray-500 mb-1">Steps</label>
                                <input
                                    type="number"
                                    min="1"
                                    max="150"
                                    value={steps}
                                    onChange={(e) => setSteps(parseInt(e.target.value))}
                                    className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm"
                                />
                            </div>
                            <div>
                                <label className="block text-xs font-medium text-gray-500 mb-1">CFG</label>
                                <input
                                    type="number"
                                    min="0"
                                    max="30"
                                    step="0.5"
                                    value={cfg}
                                    onChange={(e) => setCfg(parseFloat(e.target.value))}
                                    className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm"
                                />
                            </div>
                        </div>

                        <div>
                            <label className="block text-xs font-medium text-gray-500 mb-1">Sampler</label>
                            <select
                                value={sampler}
                                onChange={(e) => setSampler(e.target.value)}
                                className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm"
                            >
                                {samplers.map(s => (
                                    <option key={s} value={s}>{s}</option>
                                ))}
                            </select>
                        </div>

                        <div>
                            <label className="block text-xs font-medium text-gray-500 mb-1">Scheduler</label>
                            <select
                                value={scheduler}
                                onChange={(e) => setScheduler(e.target.value)}
                                className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm"
                            >
                                {schedulers.map(s => (
                                    <option key={s} value={s}>{s}</option>
                                ))}
                            </select>
                        </div>

                        <div>
                            <label className="block text-xs font-medium text-gray-500 mb-1">Seed</label>
                            <div className="flex gap-2">
                                <input
                                    type="number"
                                    value={seed}
                                    onChange={(e) => setSeed(parseInt(e.target.value))}
                                    className="flex-1 bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm"
                                />
                                <button
                                    onClick={randomizeSeed}
                                    className="p-2 bg-gray-700 hover:bg-gray-600 rounded-lg"
                                    title="Randomize Seed"
                                >
                                    <RefreshCw size={16} />
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Generate Button */}
                    <button
                        onClick={handleGenerate}
                        disabled={generating || !sourceImage?.filename || !maskImage || !selectedCheckpoint?.name}
                        className={`w-full py-4 rounded-xl font-semibold text-lg flex items-center justify-center gap-3 transition-all
                            ${generating || !sourceImage?.filename || !maskImage || !selectedCheckpoint?.name
                                ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                                : 'bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white shadow-lg shadow-purple-900/30'}
                        `}
                    >
                        {generating ? (
                            <>
                                <Loader2 className="animate-spin" size={20} />
                                Generating...
                            </>
                        ) : (
                            <>
                                <Play size={20} />
                                Generate Inpaint
                            </>
                        )}
                    </button>

                    {/* Status */}
                    {sourceImage && !maskImage && (
                        <div className="bg-yellow-900/20 border border-yellow-700/50 rounded-lg p-3 text-center">
                            <p className="text-sm text-yellow-300">
                                Draw a mask on the image to continue
                            </p>
                        </div>
                    )}

                    {/* Quick Info */}
                    {sourceImage && (
                        <div className="bg-gray-800/30 p-4 rounded-xl border border-gray-700/50">
                            <p className="text-xs text-gray-500 mb-2">Output Resolution</p>
                            <p className="text-lg font-bold text-gray-300">
                                {sourceImage.width} × {sourceImage.height}
                            </p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
