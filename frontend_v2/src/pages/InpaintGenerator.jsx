/**
 * Inpainting Generator Page
 * 
 * Dedicated page for inpainting - regenerating masked areas of an image.
 * Uses a Fabric.js canvas for mask drawing.
 */

import { useState, useEffect, useMemo } from 'react';
import { Paintbrush, Settings2, Play, Trash2, Plus, Loader2, Sparkles } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useGeneratorCore } from '../hooks/useGeneratorCore';
import { useActiveJobs } from '../hooks/useActiveJobs';
import { filesApi, generateApi, createIdempotencyKey } from '../api';
import { getApiUrl } from '../api/config';
import ImageUploader from '../components/generator/ImageUploader';
import MissingModelsDialog from '../components/generator/MissingModelsDialog';
import GeneratorReadinessPanel from '../components/generator/GeneratorReadinessPanel';
import SamplingSettings from '../components/generator/SamplingSettings';
import PromptPanel from '../components/generator/PromptPanel';
import EnhancementsSection from '../components/generator/EnhancementsSection';
import ControlNetSection from '../components/generator/ControlNetSection';
import IPAdapterSection from '../components/generator/IPAdapterSection';
import PresetManager from '../components/generator/PresetManager';
import InpaintCanvas from '../components/generator/InpaintCanvas';
import ModelSelector from '../components/ModelSelector';
import useSettingsStore from '../store/settingsStore';
import { useGeneratorJob } from '../hooks/useGeneratorJob';
import GeneratorTabs from '../components/generator/GeneratorTabs';
import { useModelDirectories } from '../hooks/useModelDirectories';
import { GENERATOR_MODEL_REQUESTS } from '../constants/modelDirectories';
import { WorkflowBuilder } from '../utils/workflowBuilder';

const EMPTY_MODELS = [];

export default function InpaintGenerator() {
    const location = useLocation();
    const [autoOpenLoraIndex, setAutoOpenLoraIndex] = useState(null);
    const {
        store: {
            prompt, negativePrompt, seed, steps, cfg, sampler, scheduler,
            sourceImage, denoise, maskImage, maskBlur,
            selectedCheckpoint, selectedVae, selectedLoras,
            setSourceImage, setDenoise, setMaskImage, setMaskBlur,
            clearSourceImage, setSelectedCheckpoint, setSelectedVae,
            clipSkip, enableFreeU, setEnableFreeU, enablePAG, setEnablePAG, pagScale, setPagScale,
            enableLatentUpscale, setEnableLatentUpscale, latentUpscaleMultiplier, setLatentUpscaleMultiplier,
            randomizeSeed, addLora, removeLora, updateLora, addControlNet, removeControlNet, updateControlNet,
            ipAdapters, addIpAdapter, removeIpAdapter, updateIpAdapter
        },
        providers, providersLoading,
        preflight: {
            isChecking: preflightChecking,
            validationResult,
            summary: validationSummary,
            isMissingModelsOpen,
            setIsMissingModelsOpen,
            runWithPreflight,
        }
    } = useGeneratorCore();

    // Canvas visibility is derived from the presence of a source image (it is
    // only ever opened when an image is loaded and closed on Clear), so there is
    // no separate state to keep in sync — avoids setState-in-effect lint errors.
    const showCanvas = !!sourceImage?.filename;
    const { data: activeJobs = [] } = useActiveJobs();
    const activeJobCount = activeJobs.length;
    const { modelsByKey } = useModelDirectories(GENERATOR_MODEL_REQUESTS);
    const checkpoints = modelsByKey.checkpoints ?? EMPTY_MODELS;
    const controlNetModels = modelsByKey.controlNetModels ?? EMPTY_MODELS;
    const vaeModels = modelsByKey.vaeModels ?? EMPTY_MODELS;

    const autoRandomizeSeed = useSettingsStore(state => state.settings.generator.autoRandomizeSeed);

    // Check for pre-loaded image from navigation state
    useEffect(() => {
        if (location.state?.sourceImage) {
            setSourceImage(location.state.sourceImage);
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

    const validateInpaint = () => {
        if (!sourceImage?.filename) return 'Please upload a source image first';
        if (!maskImage) return 'Please draw a mask on the image';
        if (!selectedCheckpoint?.name) return 'Please select a checkpoint';
        return null;
    };

    const runSubmission = async ({ setProgress }) => {
        const checkpointToUse = inpaintCheckpoint?.name || selectedCheckpoint.name;

        const maskResult = await filesApi.uploadMask(
            maskImage,
            sourceImage.filename,
        );

        setProgress({ value: 0, max: 100, status: 'starting', node: 'Initializing...' });

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
            growMask: 6,
            clipSkip,
            enableFreeU,
            enablePAG,
            pagScale,
            enableLatentUpscale,
            latentUpscaleMultiplier,
            ipAdapters,
            controlnets: []
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
            clipSkip,
            enableFreeU,
            enablePAG,
            pagScale,
            usedInpaintModel: !!inpaintCheckpoint
        };

        return runWithPreflight(workflow, {
            onValid: async () => generateApi.workflow(workflow, metadata, {
                idempotencyKey: createIdempotencyKey('generate-inpaint')
            }),
        });
    };

    const { progress, generating, handleGenerate } = useGeneratorJob({
        runSubmission,
        type: 'inpaint',
        setGeneratingOnQueue: true,
        startingNode: 'Uploading mask...',
        validate: validateInpaint,
        randomizeSeed,
        autoRandomizeSeed,
    });

    const handleClearAll = () => {
        clearSourceImage();
    };

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
                <div className="lg:col-span-2 space-y-4 lg:space-y-4 md:space-y-6">

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
                    <PromptPanel />

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
                        <ControlNetSection
                            controlnets={[]}
                            addControlNet={addControlNet}
                            removeControlNet={removeControlNet}
                            updateControlNet={updateControlNet}
                            controlNetModels={controlNetModels}
                        />

                        <IPAdapterSection
                            ipAdapters={ipAdapters}
                            addIpAdapter={addIpAdapter}
                            removeIpAdapter={removeIpAdapter}
                            updateIpAdapter={updateIpAdapter}
                        />

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

                        <EnhancementsSection
                            enableFreeU={enableFreeU}
                            setEnableFreeU={setEnableFreeU}
                            enablePAG={enablePAG}
                            setEnablePAG={setEnablePAG}
                            pagScale={pagScale}
                            setPagScale={setPagScale}
                            enableLatentUpscale={enableLatentUpscale}
                            setEnableLatentUpscale={setEnableLatentUpscale}
                            latentUpscaleMultiplier={latentUpscaleMultiplier}
                            setLatentUpscaleMultiplier={setLatentUpscaleMultiplier}
                        />

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
                <div className="space-y-4 lg:space-y-4 md:space-y-6">
                    <GeneratorReadinessPanel
                        providers={providers}
                        providersLoading={providersLoading}
                        validationSummary={validationSummary}
                        isChecking={preflightChecking}
                        title="Inpaint Runway"
                        hint="Check runtime health and workflow availability before regenerating the masked region."
                    />

                    <PresetManager />

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

                    <SamplingSettings />

                    {/* Generate Button */}
                    <div className="flex gap-2">
                        <button
                            onClick={() => handleGenerate({ shouldRedirect: false, trackQueuedJob: false })}
                            disabled={generating || !sourceImage?.filename || !maskImage || !selectedCheckpoint?.name}
                            className={`flex-1 h-14 rounded-xl font-bold text-base shadow-lg transition-all border border-gray-700 flex items-center justify-center ${generating || !sourceImage?.filename || !maskImage || !selectedCheckpoint?.name
                                ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
                                : 'bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white'
                                }`}
                            title="Add to queue"
                        >
                            <Plus size={20} />
                        </button>

                        <button
                            onClick={() => handleGenerate({ shouldRedirect: true, trackQueuedJob: true })}
                            disabled={generating || !sourceImage?.filename || !maskImage || !selectedCheckpoint?.name}
                            className={`flex-[4] relative overflow-hidden h-14 rounded-xl font-bold text-lg flex items-center justify-center gap-3 transition-all
                                ${generating || !sourceImage?.filename || !maskImage || !selectedCheckpoint?.name
                                    ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                                    : 'bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white shadow-lg shadow-purple-900/30'}
                            `}
                        >
                            {generating ? (
                                <>
                                    <Loader2 className="animate-spin" size={20} />
                                    {progress?.node || 'Generating...'}
                                </>
                            ) : (
                                <>
                                    <Play size={20} />
                                    Generate Inpaint
                                </>
                            )}
                            {generating && progress && (
                                <div className="absolute top-0 left-0 h-1 bg-gradient-to-r from-purple-400 to-pink-400 transition-all duration-300 ease-out" style={{ width: `${progress.value}%` }} />
                            )}
                        </button>
                    </div>

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

            <MissingModelsDialog
                isOpen={isMissingModelsOpen}
                onClose={() => setIsMissingModelsOpen(false)}
                validationResult={validationResult}
            />
        </div>
    );
}
