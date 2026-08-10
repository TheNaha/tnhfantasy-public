/**
 * Img2Img Generator Page
 * 
 * Dedicated page for image-to-image generation.
 * Uses a source image and transforms it based on prompts and denoise setting.
 */

import { useState, useEffect } from 'react';
import { ImageIcon, Settings2, Play, Trash2, Plus, Loader2, Link as LinkIcon } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useGeneratorCore } from '../hooks/useGeneratorCore';
import { useActiveJobs } from '../hooks/useActiveJobs';
import { generateApi, createIdempotencyKey } from '../api';
import ImageUploader from '../components/generator/ImageUploader';
import MissingModelsDialog from '../components/generator/MissingModelsDialog';
import GeneratorReadinessPanel from '../components/generator/GeneratorReadinessPanel';
import ControlNetSection from '../components/generator/ControlNetSection';
import IPAdapterSection from '../components/generator/IPAdapterSection';
import EnhancementsSection from '../components/generator/EnhancementsSection';
import PromptPanel from '../components/generator/PromptPanel';
import SamplingSettings from '../components/generator/SamplingSettings';
import PresetManager from '../components/generator/PresetManager';
import ModelSelector from '../components/ModelSelector';
import useSettingsStore from '../store/settingsStore';
import { useGeneratorJob } from '../hooks/useGeneratorJob';
import GeneratorTabs from '../components/generator/GeneratorTabs';
import { useModelDirectories } from '../hooks/useModelDirectories';
import { GENERATOR_MODEL_REQUESTS } from '../constants/modelDirectories';
import { WorkflowBuilder } from '../utils/workflowBuilder';

export default function Img2ImgGenerator() {
    const location = useLocation();
    const [autoOpenLoraIndex, setAutoOpenLoraIndex] = useState(null);
    const {
        store: {
            prompt, negativePrompt, seed, steps, cfg, sampler, scheduler,
            sourceImage, denoise, setSourceImage, setDenoise, clearSourceImage,
            setSelectedCheckpoint, setSelectedVae,
            selectedCheckpoint, selectedVae, selectedLoras,
            clipSkip, enableFreeU, setEnableFreeU, enablePAG, setEnablePAG, pagScale, setPagScale,
            enableLatentUpscale, setEnableLatentUpscale, latentUpscaleMultiplier, setLatentUpscaleMultiplier,
            randomizeSeed, addLora, removeLora, updateLora, controlnets, addControlNet, removeControlNet, updateControlNet,
            ipAdapters, addIpAdapter, removeIpAdapter, updateIpAdapter,
            adetailerInpaintMasked, setAdetailerInpaintMasked
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

    const { modelsByKey } = useModelDirectories(GENERATOR_MODEL_REQUESTS);
    const checkpoints = modelsByKey.checkpoints || [];
    const vaeModels = modelsByKey.vaeModels || [];
    const controlNetModels = modelsByKey.controlNetModels || [];
    const adetailerModels = modelsByKey.adetailerModels || [];

    const { data: activeJobs = [] } = useActiveJobs();
    const activeJobCount = activeJobs.length;

    const autoRandomizeSeed = useSettingsStore(state => state.settings.generator.autoRandomizeSeed);

    // Check for pre-loaded image from navigation state
    useEffect(() => {
        if (location.state?.sourceImage) {
            setSourceImage(location.state.sourceImage);
        }
    }, [location.state, setSourceImage]);

    const validateImg2Img = () => {
        if (!sourceImage?.filename) return 'Please upload a source image first';
        if (!selectedCheckpoint?.name) return 'Please select a checkpoint';
        return null;
    };

    const runSubmission = async () => {
        const builder = new WorkflowBuilder();
        const workflow = builder.buildImg2Img({
            inputImage: sourceImage.filename,
            prompt,
            negativePrompt,
            seed,
            steps,
            cfg,
            sampler,
            scheduler,
            denoise,
            checkpoint: selectedCheckpoint.name,
            loras: selectedLoras,
            vae: selectedVae,
            clipSkip,
            enableFreeU,
            enablePAG,
            pagScale,
            enableLatentUpscale,
            latentUpscaleMultiplier,
            ipAdapters,
            controlnets: controlnets
        });

        const metadata = {
            type: 'img2img',
            prompt,
            negativePrompt,
            seed,
            steps,
            cfg,
            sampler,
            scheduler,
            denoise,
            width: sourceImage.width,
            height: sourceImage.height,
            sourceImage: sourceImage.filename,
            checkpoint: selectedCheckpoint,
            vae: selectedVae,
            loras: selectedLoras,
            clipSkip,
            enableFreeU,
            enablePAG,
            pagScale,
            enableLatentUpscale,
            ipAdapters,
            controlnets
        };

        return runWithPreflight(workflow, {
            onValid: async () => generateApi.workflow(workflow, metadata, {
                idempotencyKey: createIdempotencyKey('generate-img2img')
            }),
        });
    };

    const { progress, generating, handleGenerate } = useGeneratorJob({
        runSubmission,
        type: 'img2img',
        setGeneratingOnQueue: true,
        validate: validateImg2Img,
        randomizeSeed,
        autoRandomizeSeed,
    });

    return (
        <div className="pb-24">
            {/* Header with Tabs */}
            <div className="max-w-6xl mx-auto mb-6">
                <div className="flex justify-between items-center mb-4">
                    <h1 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-orange-400 to-red-500">
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
                {/* Left Column: Image & Settings */}
                <div className="lg:col-span-2 space-y-4 lg:space-y-4 md:space-y-6">

                    {/* Source Image */}
                    <div className="space-y-3 pb-4 border-b border-gray-800">
                        <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2">
                            <ImageIcon size={18} className="text-orange-400" />
                            Source Image
                        </h3>
                        <ImageUploader
                            image={sourceImage}
                            onImageSelect={setSourceImage}
                            onClear={clearSourceImage}
                        />
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

                        <EnhancementsSection
                            adetailerInpaintMasked={adetailerInpaintMasked}
                            setAdetailerInpaintMasked={setAdetailerInpaintMasked}
                            adetailerModels={adetailerModels}
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
                        title="Img2Img Runway"
                        hint="Check provider health and model availability before transforming the source image."
                    />

                    <PresetManager />

                    {/* Denoise Strength - KEY Img2Img Parameter */}
                    <div className="space-y-3 pb-4 border-b border-gray-800">
                        <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2 text-orange-400">
                            <LinkIcon size={18} />
                            Denoise Strength
                        </h3>
                        <div className="space-y-2">
                            <div className="flex justify-between text-sm">
                                <span className="text-gray-400">Preserve Original</span>
                                <span className="text-gray-400">Full Regeneration</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="1"
                                step="0.05"
                                value={denoise}
                                onChange={(e) => setDenoise(parseFloat(e.target.value))}
                                className="w-full accent-orange-500"
                            />
                            <div className="text-center">
                                <span className="text-2xl font-bold text-orange-400">{denoise.toFixed(2)}</span>
                            </div>
                            <p className="text-xs text-gray-500 text-center">
                                Lower = More like original • Higher = More creative
                            </p>
                        </div>
                    </div>

                    <SamplingSettings />

                    {/* Generate Button */}
                    <div className="flex gap-2">
                        <button
                            onClick={() => handleGenerate({ shouldRedirect: false, trackQueuedJob: false })}
                            disabled={generating || !sourceImage?.filename || !selectedCheckpoint?.name}
                            className={`flex-1 h-14 rounded-xl font-bold text-base shadow-lg transition-all border border-gray-700 flex items-center justify-center ${generating || !sourceImage?.filename || !selectedCheckpoint?.name
                                ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
                                : 'bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white'
                                }`}
                            title="Add to queue"
                        >
                            <Plus size={20} />
                        </button>

                        <button
                            onClick={() => handleGenerate({ shouldRedirect: true, trackQueuedJob: true })}
                            disabled={generating || !sourceImage?.filename || !selectedCheckpoint?.name}
                            className={`flex-[4] relative overflow-hidden h-14 rounded-xl font-bold text-lg flex items-center justify-center gap-3 transition-all
                                ${generating || !sourceImage?.filename || !selectedCheckpoint?.name
                                    ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                                    : 'bg-gradient-to-r from-orange-600 to-red-600 hover:from-orange-500 hover:to-red-500 text-white shadow-lg shadow-orange-900/30'}
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
                                    Generate Img2Img
                                </>
                            )}
                            {generating && progress && (
                                <div className="absolute top-0 left-0 h-1 bg-gradient-to-r from-orange-400 to-yellow-400 transition-all duration-300 ease-out" style={{ width: `${progress.value}%` }} />
                            )}
                        </button>
                    </div>

                    {/* Quick Info */}
                    {sourceImage && (
                        <div className="bg-gray-800/30 p-4 rounded-xl border border-gray-700/50">
                            <p className="text-xs text-gray-500 mb-2">Output Resolution</p>
                            <p className="text-lg font-bold text-gray-300">
                                {sourceImage.width} × {sourceImage.height}
                            </p>
                            <p className="text-xs text-gray-500 mt-2">
                                Output will match source image dimensions
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
