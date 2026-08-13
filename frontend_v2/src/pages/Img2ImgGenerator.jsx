/**
 * Img2Img Generator Page
 * 
 * Dedicated page for image-to-image generation.
 * Uses a source image and transforms it based on prompts and denoise setting.
 */

import { useState, useEffect } from 'react';
import { ImageIcon, Settings2, Link as LinkIcon } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useGeneratorCore } from '../hooks/useGeneratorCore';
import { useActiveJobs } from '../hooks/useActiveJobs';
import { generateApi, createIdempotencyKey } from '../api';
import ImageUploader from '../components/generator/ImageUploader';
import ModelMetadataModal from '../components/ModelMetadataModal';
import GeneratorReadinessPanel from '../components/generator/GeneratorReadinessPanel';
import ModelSection from '../components/generator/ModelSection';
import ControlNetSection from '../components/generator/ControlNetSection';
import IPAdapterSection from '../components/generator/IPAdapterSection';
import EnhancementsSection from '../components/generator/EnhancementsSection';
import PromptPanel from '../components/generator/PromptPanel';
import SamplingSettings from '../components/generator/SamplingSettings';
import PresetManager from '../components/generator/PresetManager';
import useSettingsStore from '../store/settingsStore';
import { useGeneratorJob } from '../hooks/useGeneratorJob';
import { useModelDirectories } from '../hooks/useModelDirectories';
import { GENERATOR_MODEL_REQUESTS } from '../constants/modelDirectories';
import { WorkflowBuilder } from '../utils/workflowBuilder';
import GeneratorShell from '../components/generator/GeneratorShell';
import GenerateActionBar from '../components/generator/GenerateActionBar';
import ResolutionSettings from '../components/generator/ResolutionSettings';

const EMPTY_MODELS = [];

export default function Img2ImgGenerator() {
    const location = useLocation();
    const [autoOpenLoraIndex, setAutoOpenLoraIndex] = useState(null);
    const [viewingMetadata, setViewingMetadata] = useState(null);
    const {
        store: {
            prompt, negativePrompt, seed, steps, cfg, sampler, scheduler,
            sourceImage, denoise, setSourceImage, setDenoise, clearSourceImage,
            setSelectedCheckpoint, setSelectedVae,
            selectedCheckpoint, selectedVae, selectedLoras,
            clipSkip, enableFreeU, setEnableFreeU, enablePAG, setEnablePAG, pagScale, setPagScale,
            enableLatentUpscale, setEnableLatentUpscale, latentUpscaleMultiplier, setLatentUpscaleMultiplier,
            randomizeSeed, addLora, removeLora, updateLora, controlnets, addControlNet, removeControlNet, updateControlNet,
            setPrompt, setNegativePrompt, addTriggerWords,
            selectedClip, setSelectedClip, selectedClip2, setSelectedClip2,
            ipAdapters, addIpAdapter, removeIpAdapter, updateIpAdapter,
            adetailer, setAdetailer, adetailerModel, setAdetailerModel,
            adetailerPrompt, setAdetailerPrompt, adetailerSteps, setAdetailerSteps,
            adetailerDenoise, setAdetailerDenoise, adetailerInpaintMasked, setAdetailerInpaintMasked
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
    const checkpoints = modelsByKey.checkpoints ?? EMPTY_MODELS;
    const unetModels = modelsByKey.unetModels ?? EMPTY_MODELS;
    const vaeModels = modelsByKey.vaeModels ?? EMPTY_MODELS;
    const clipModels = modelsByKey.clipModels ?? EMPTY_MODELS;
    const embeddingModels = modelsByKey.embeddingModels ?? EMPTY_MODELS;
    const controlNetModels = modelsByKey.controlNetModels ?? EMPTY_MODELS;
    const adetailerModels = modelsByKey.adetailerModels ?? EMPTY_MODELS;

    const autoRandomizeSeed = useSettingsStore(state => state.settings.generator.autoRandomizeSeed);
    const { data: activeJobs = [] } = useActiveJobs();
    const activeJobCount = activeJobs.length;

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
            controlnets: controlnets,
            adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise, adetailerInpaintMasked
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
            controlnets,
            adetailer, adetailerModel
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

    const canGenerate = generating || !sourceImage?.filename || !selectedCheckpoint?.name;

    return (
        <>
            <GeneratorShell
            accentClass="from-orange-400 to-red-500"
            activeJobCount={activeJobCount}
            isMissingModelsOpen={isMissingModelsOpen}
            setIsMissingModelsOpen={setIsMissingModelsOpen}
            validationResult={validationResult}
            leftColumn={(
                <>
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
                        <ModelSection
                            selectedCheckpoint={selectedCheckpoint}
                            setSelectedCheckpoint={setSelectedCheckpoint}
                            selectedVae={selectedVae}
                            setSelectedVae={setSelectedVae}
                            selectedClip={selectedClip}
                            setSelectedClip={setSelectedClip}
                            selectedClip2={selectedClip2}
                            setSelectedClip2={setSelectedClip2}
                            selectedLoras={selectedLoras}
                            addLora={addLora}
                            removeLora={removeLora}
                            updateLora={updateLora}
                            addTriggerWords={addTriggerWords}
                            prompt={prompt}
                            negativePrompt={negativePrompt}
                            setPrompt={setPrompt}
                            setNegativePrompt={setNegativePrompt}
                            checkpoints={checkpoints}
                            unetModels={unetModels}
                            vaeModels={vaeModels}
                            clipModels={clipModels}
                            embeddingModels={embeddingModels}
                            setViewingMetadata={setViewingMetadata}
                            providers={providers}
                            providersLoading={providersLoading}
                            autoOpenLoraIndex={autoOpenLoraIndex}
                            setAutoOpenLoraIndex={setAutoOpenLoraIndex}
                        />

                        <ControlNetSection
                            controlnets={controlnets}
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
                            adetailer={adetailer}
                            setAdetailer={setAdetailer}
                            adetailerModel={adetailerModel}
                            setAdetailerModel={setAdetailerModel}
                            adetailerPrompt={adetailerPrompt}
                            setAdetailerPrompt={setAdetailerPrompt}
                            adetailerSteps={adetailerSteps}
                            setAdetailerSteps={setAdetailerSteps}
                            adetailerDenoise={adetailerDenoise}
                            setAdetailerDenoise={setAdetailerDenoise}
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
                    </div>
                </>
            )}
            rightColumn={(
                <>
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

                    <GenerateActionBar
                        generating={generating}
                        progress={progress}
                        disabled={canGenerate}
                        onQueue={() => handleGenerate({ shouldRedirect: false, trackQueuedJob: false })}
                        onGenerate={() => handleGenerate({ shouldRedirect: true, trackQueuedJob: true })}
                        label="Generate Img2Img"
                        gradientClass="bg-gradient-to-r from-orange-600 to-red-600 hover:from-orange-500 hover:to-red-500 text-white shadow-lg shadow-orange-900/30"
                        progressBarClass="from-orange-400 to-yellow-400"
                    />

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
                </>
            )}
        />

            {viewingMetadata && (
                <ModelMetadataModal
                    metadata={viewingMetadata}
                    providers={providers}
                    providersLoading={providersLoading}
                    onClose={() => setViewingMetadata(null)}
                />
            )}
        </>
    );
}
