import React, { useState, useEffect } from 'react';
import { FolderOpen, Loader2 } from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';
import { WorkflowBuilder } from '../utils/workflowBuilder';
import { useGeneratorStore } from '../store/generatorStore';
import { useActiveJobs } from '../hooks/useActiveJobs';
import { useTrackJob } from '../hooks/useTrackJob';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import ModelMetadataModal from '../components/ModelMetadataModal';
import MissingModelsDialog from '../components/generator/MissingModelsDialog';
import GeneratorReadinessPanel from '../components/generator/GeneratorReadinessPanel';
import PromptPanel from '../components/generator/PromptPanel';
import GeneratorTabs from '../components/generator/GeneratorTabs';
import ModelSection from '../components/generator/ModelSection';
import { isUnetModel, isFluxModel, isAuraFlowModel, isPonyModel } from '../utils/modelType';
import ControlNetSection from '../components/generator/ControlNetSection';
import EnhancementsSection from '../components/generator/EnhancementsSection';
import ParametersPanel from '../components/generator/ParametersPanel';
import GenerateButtonBar from '../components/generator/GenerateButtonBar';
import { useNavigate } from 'react-router-dom';
import { useModelDirectories } from '../hooks/useModelDirectories';
import useGenerationPreflight from '../hooks/useGenerationPreflight';
import { GENERATOR_MODEL_REQUESTS } from '../constants/modelDirectories';
import useProvidersPageData from '../hooks/useProvidersPageData';
import toast from 'react-hot-toast';
import useSettingsStore, { useSettings } from '../store/settingsStore';
import { generateApi, createIdempotencyKey } from '../api';

const generatorSelector = (state) => ({
    prompt: state.prompt,
    negativePrompt: state.negativePrompt,
    seed: state.seed,
    steps: state.steps,
    cfg: state.cfg,
    sampler: state.sampler,
    scheduler: state.scheduler,
    width: state.width,
    height: state.height,
    batchSize: state.batchSize,
    selectedCheckpoint: state.selectedCheckpoint,
    selectedVae: state.selectedVae,
    selectedClip: state.selectedClip,
    selectedClip2: state.selectedClip2,
    selectedLoras: state.selectedLoras,
    controlnets: state.controlnets,
    hiresFix: state.hiresFix,
    hiresUpscaler: state.hiresUpscaler,
    hiresDenoise: state.hiresDenoise,
    hiresUpscale: state.hiresUpscale,
    hiresSteps: state.hiresSteps,
    adetailer: state.adetailer,
    adetailerModel: state.adetailerModel,
    adetailerPrompt: state.adetailerPrompt,
    adetailerSteps: state.adetailerSteps,
    adetailerDenoise: state.adetailerDenoise,
    adetailerInpaintMasked: state.adetailerInpaintMasked,
    setPrompt: state.setPrompt,
    setNegativePrompt: state.setNegativePrompt,
    setSeed: state.setSeed,
    setSteps: state.setSteps,
    setCfg: state.setCfg,
    setSampler: state.setSampler,
    setScheduler: state.setScheduler,
    setWidth: state.setWidth,
    setHeight: state.setHeight,
    setBatchSize: state.setBatchSize,
    setAspectRatioLocked: state.setAspectRatioLocked,
    setSelectedCheckpoint: state.setSelectedCheckpoint,
    setSelectedVae: state.setSelectedVae,
    setSelectedClip: state.setSelectedClip,
    setSelectedClip2: state.setSelectedClip2,
    setHiresFix: state.setHiresFix,
    setHiresUpscaler: state.setHiresUpscaler,
    setHiresDenoise: state.setHiresDenoise,
    setHiresUpscale: state.setHiresUpscale,
    setHiresSteps: state.setHiresSteps,
    setAdetailer: state.setAdetailer,
    setAdetailerModel: state.setAdetailerModel,
    setAdetailerPrompt: state.setAdetailerPrompt,
    setAdetailerSteps: state.setAdetailerSteps,
    setAdetailerDenoise: state.setAdetailerDenoise,
    setAdetailerInpaintMasked: state.setAdetailerInpaintMasked,
    randomizeSeed: state.randomizeSeed,
    addLora: state.addLora,
    removeLora: state.removeLora,
    updateLora: state.updateLora,
    addControlNet: state.addControlNet,
    removeControlNet: state.removeControlNet,
    updateControlNet: state.updateControlNet,
    addTriggerWords: state.addTriggerWords,
    aspectRatioLocked: state.aspectRatioLocked,
});

export default function SimpleGenerator() {
    const navigate = useNavigate();
    const settings = useSettings();
    const [generating, setGenerating] = useState(false);
    const [viewingMetadata, setViewingMetadata] = useState(null);
    const [currentJobId, setCurrentJobId] = useState(null);
    const [progress, setProgress] = useState(null);
    const [autoOpenLoraIndex, setAutoOpenLoraIndex] = useState(null);

    const {
        prompt, negativePrompt, seed, steps, cfg, sampler, scheduler, width, height, batchSize,
        selectedCheckpoint, selectedVae, selectedClip, selectedClip2, selectedLoras, controlnets,
        hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps,
        adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise, adetailerInpaintMasked,
        setPrompt, setNegativePrompt, setSeed, setSteps, setCfg, setSampler, setScheduler, setWidth, setHeight, setBatchSize, setAspectRatioLocked,
        setSelectedCheckpoint, setSelectedVae, setSelectedClip, setSelectedClip2,
        setHiresFix, setHiresUpscaler, setHiresDenoise, setHiresUpscale, setHiresSteps,
        setAdetailer, setAdetailerModel, setAdetailerPrompt, setAdetailerSteps, setAdetailerDenoise, setAdetailerInpaintMasked,
        randomizeSeed, addLora, removeLora, updateLora, addControlNet, removeControlNet, updateControlNet, addTriggerWords,
        aspectRatioLocked
    } = useGeneratorStore(useShallow(generatorSelector));

    const { modelsByKey } = useModelDirectories(GENERATOR_MODEL_REQUESTS);
    const checkpoints = modelsByKey.checkpoints || [];
    const controlNetModels = modelsByKey.controlNetModels || [];
    const upscalerModels = modelsByKey.upscalerModels || [];
    const vaeModels = modelsByKey.vaeModels || [];
    const unetModels = modelsByKey.unetModels || [];
    const clipModels = modelsByKey.clipModels || [];
    const embeddingModels = modelsByKey.embeddingModels || [];
    const adetailerModels = modelsByKey.adetailerModels || [];

    const { data: activeJobs = [] } = useActiveJobs();
    const activeJobCount = activeJobs.length;
    const { data: trackedJob } = useTrackJob(currentJobId);

    const autoRandomizeSeed = useSettingsStore(state => state.settings.generator.autoRandomizeSeed);

    const { providers, isLoading: providersLoading } = useProvidersPageData();
    const {
        isChecking: preflightChecking,
        validationResult,
        summary: validationSummary,
        isMissingModelsOpen,
        setIsMissingModelsOpen,
        runWithPreflight,
    } = useGenerationPreflight();

    useKeyboardShortcuts();

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

    useEffect(() => {
        if (!currentJobId || !trackedJob) return;

        const isQueued = trackedJob.status === 'pending' || trackedJob.status === 'queued';
        const progressValue = trackedJob.overall_progress ?? trackedJob.progress ?? 0;

        if (trackedJob.status === 'completed') {
            setGenerating(false);
            setProgress(null);
            setCurrentJobId(null);
            toast.success('Generation complete!', { icon: '✨' });
            if (settings.generator.redirectAfterGenerate) {
                setTimeout(() => navigate('/'), settings.generator.redirectDelay);
            }
            return;
        }

        if (trackedJob.status === 'failed') {
            setGenerating(false);
            setProgress(null);
            setCurrentJobId(null);
            toast.error(`Generation failed: ${trackedJob.error || 'Unknown error'}`);
            return;
        }

        if (trackedJob.status === 'cancelled') {
            setGenerating(false);
            setProgress(null);
            setCurrentJobId(null);
            toast('Generation cancelled');
            return;
        }

        // Otherwise it is active
        setGenerating(true);
        setProgress({
            value: progressValue,
            max: 100,
            status: isQueued ? 'queued' : trackedJob.status,
            node: trackedJob.message || (isQueued ? 'Job queued...' : `${progressValue}%`),
        });
    }, [
        trackedJob, currentJobId,
        navigate, settings.generator.redirectAfterGenerate, settings.generator.redirectDelay,
    ]);

    const buildSimpleWorkflowPayload = (jobSeed = seed) => {
        const builder = new WorkflowBuilder();
        const isUnet = isUnetModel(selectedCheckpoint);

        let effectiveVae = selectedVae;
        if (effectiveVae === "Baked in" && isUnet) {
            if (isFluxModel(selectedCheckpoint)) effectiveVae = "ae.safetensors";
            else if (isAuraFlowModel(selectedCheckpoint) || isPonyModel(selectedCheckpoint)) effectiveVae = "sdxl_vae.safetensors";
        }

        const workflow = builder.build({
            prompt, negativePrompt, seed: jobSeed, steps, cfg, sampler, scheduler,
            width, height, batchSize,
            checkpoint: isUnet ? null : selectedCheckpoint?.name,
            unet: isUnet ? selectedCheckpoint?.name : null,
            clip: isUnet ? selectedClip : null,
            clip2: (isUnet && (isFluxModel(selectedCheckpoint) || isPonyModel(selectedCheckpoint))) ? selectedClip2 : null,
            vae: effectiveVae,
            loras: selectedLoras, controlnets,
            hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps,
            adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise, adetailerInpaintMasked,
            modelType: isFluxModel(selectedCheckpoint) ? 'flux' : (isPonyModel(selectedCheckpoint) || isAuraFlowModel(selectedCheckpoint)) ? 'sdxl' : 'sd15'
        });

        const metadata = {
            prompt, negativePrompt, seed: jobSeed, steps, cfg, sampler, scheduler,
            width, height, batchSize,
            checkpoint: selectedCheckpoint, vae: selectedVae, loras: selectedLoras,
            embeddings: extractEmbeddingsFromPrompt(prompt, negativePrompt),
            hiresFix, hiresUpscaler, adetailer, adetailerModel
        };

        return { workflow, metadata };
    };

    const handleGenerate = async ({ shouldRedirect = true, trackQueuedJob = true } = {}) => {
        if (trackQueuedJob) {
            setGenerating(true);
            setProgress({ value: 0, max: 100, status: 'starting', node: 'Initializing...' });
        }

        try {
            const { workflow, metadata } = buildSimpleWorkflowPayload();
            const submission = await runWithPreflight(workflow, {
                onValid: async () => generateApi.workflow(workflow, metadata, {
                    idempotencyKey: createIdempotencyKey('generate-simple')
                }),
            });

            if (!submission.ok) {
                if (trackQueuedJob) {
                    setGenerating(false);
                    setProgress(null);
                }
                return;
            }

            const data = submission.submissionResult;

            if (data && data.id) {
                if (trackQueuedJob) {
                    setCurrentJobId(data.id);
                    setGenerating(true);
                    setProgress({ value: 0, max: 100, status: 'queued', node: 'Job queued...' });
                    toast.success('Job queued!', { icon: '⏳' });
                } else {
                    toast.success('Added to queue!', { icon: '➕' });
                }

                if (shouldRedirect) navigate('/');
                if (autoRandomizeSeed) randomizeSeed();
            }

        } catch (e) {
            toast.error("Error: " + e.message);
            if (trackQueuedJob) {
                setGenerating(false);
                setProgress(null);
            }
        }
    };

    const handleGenerateVariations = async (count) => {
        setGenerating(true);

        try {
            const payloads = [];
            for (let i = 0; i < count; i++) {
                const variationSeed = Math.floor(Math.random() * Number.MAX_SAFE_INTEGER);
                payloads.push({
                    ...buildSimpleWorkflowPayload(variationSeed),
                    variationSeed,
                    index: i,
                });
            }

            const validation = await runWithPreflight(payloads[0]?.workflow);
            if (!validation.ok) return;

            const jobs = payloads.map(({ workflow, metadata, index }) => (
                generateApi.workflow(workflow, metadata, {
                    idempotencyKey: createIdempotencyKey(`generate-variation-${index}`)
                })
            ));

            await Promise.all(jobs);
            toast.success(`Queued ${count} variations!`, { icon: '🎲' });
            if (autoRandomizeSeed) randomizeSeed();
            navigate('/');
        } catch (e) {
            toast.error("Error: " + e.message);
        } finally {
            setGenerating(false);
        }
    };

    return (
        <div className="pb-24">
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
                <GeneratorTabs />
            </div>

            <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-3 lg:gap-8">
                <div className="lg:col-span-2 space-y-3 lg:space-y-6 order-last lg:order-none">
                    <PromptPanel />

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

                    <EnhancementsSection
                        hiresFix={hiresFix}
                        setHiresFix={setHiresFix}
                        hiresUpscaler={hiresUpscaler}
                        setHiresUpscaler={setHiresUpscaler}
                        hiresDenoise={hiresDenoise}
                        setHiresDenoise={setHiresDenoise}
                        hiresUpscale={hiresUpscale}
                        setHiresUpscale={setHiresUpscale}
                        hiresSteps={hiresSteps}
                        setHiresSteps={setHiresSteps}
                        upscalerModels={upscalerModels}
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
                    />
                </div>

                <div className="order-first lg:order-none space-y-4 lg:space-y-6">
                    <GeneratorReadinessPanel
                        providers={providers}
                        providersLoading={providersLoading}
                        validationSummary={validationSummary}
                        isChecking={preflightChecking}
                        title="Generation Runway"
                        hint="Provider health and model checks before you commit a generation."
                    />

                    <ParametersPanel
                        width={width}
                        height={height}
                        setWidth={setWidth}
                        setHeight={setHeight}
                        batchSize={batchSize}
                        setBatchSize={setBatchSize}
                        steps={steps}
                        setSteps={setSteps}
                        cfg={cfg}
                        setCfg={setCfg}
                        seed={seed}
                        setSeed={setSeed}
                        sampler={sampler}
                        setSampler={setSampler}
                        scheduler={scheduler}
                        setScheduler={setScheduler}
                        aspectRatioLocked={aspectRatioLocked}
                        setAspectRatioLocked={setAspectRatioLocked}
                        autoRandomizeSeed={autoRandomizeSeed}
                        randomizeSeed={randomizeSeed}
                    />

                    <div className="hidden md:block">
                        <GenerateButtonBar
                            generating={generating}
                            progress={progress}
                            prompt={prompt}
                            onGenerate={() => handleGenerate({ shouldRedirect: true, trackQueuedJob: true })}
                            onQueue={() => handleGenerate({ shouldRedirect: false, trackQueuedJob: false })}
                            onGenerateVariations={handleGenerateVariations}
                        />
                    </div>
                </div>
            </div>

            <div className="h-20 md:hidden"></div>

            <div className="fixed bottom-0 left-0 right-0 p-3 bg-gray-900/95 backdrop-blur-xl border-t border-gray-800 md:hidden z-30 pb-safe">
                <GenerateButtonBar
                    generating={generating}
                    progress={progress}
                    prompt={prompt}
                    onGenerate={() => handleGenerate({ shouldRedirect: true, trackQueuedJob: true })}
                    onQueue={() => handleGenerate({ shouldRedirect: false, trackQueuedJob: false })}
                    onGenerateVariations={handleGenerateVariations}
                />
            </div>

            {viewingMetadata && (
                <ModelMetadataModal
                    metadata={viewingMetadata}
                    providers={providers}
                    providersLoading={providersLoading}
                    onClose={() => setViewingMetadata(null)}
                />
            )}

            <MissingModelsDialog
                isOpen={isMissingModelsOpen}
                onClose={() => setIsMissingModelsOpen(false)}
                validationResult={validationResult}
            />

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
