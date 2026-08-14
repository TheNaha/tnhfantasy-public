import { FolderOpen } from 'lucide-react';
import { useGeneratorCore } from '../hooks/useGeneratorCore';
import toast from 'react-hot-toast';
import useSettingsStore from '../store/settingsStore';
import { generateApi, createIdempotencyKey } from '../api';

// WorkflowBuilder moved to backend
import { useGeneratorJob } from '../hooks/useGeneratorJob';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { isUnetModel, isFluxModel, isAuraFlowModel, isPonyModel } from '../utils/modelType';
import { useNavigate } from 'react-router-dom';
import UnifiedGeneratorLayout from '../components/generator/UnifiedGeneratorLayout';
import ResolutionSettings from '../components/generator/ResolutionSettings';
import GenerateButtonBar from '../components/generator/GenerateButtonBar';

export default function SimpleGenerator() {
    const navigate = useNavigate();
    const {
        store: {
            prompt, negativePrompt, seed, steps, cfg, sampler, scheduler, width, height, batchSize,
            selectedCheckpoint, selectedVae, selectedClip, selectedClip2, selectedLoras, controlnets,
            hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps,
            adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise, adetailerInpaintMasked,
            clipSkip, enableFreeU, enablePAG, pagScale,
            enableLatentUpscale, latentUpscaleMultiplier,
            randomizeSeed,
            ipAdapters
        },
        preflight: {
            runWithPreflight,
        }
    } = useGeneratorCore();

    const autoRandomizeSeed = useSettingsStore(state => state.settings.generator.autoRandomizeSeed);

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

    const buildSimpleWorkflowPayload = (jobSeed = seed) => {
        const isUnet = isUnetModel(selectedCheckpoint);

        let effectiveVae = selectedVae;
        if (effectiveVae === "Baked in" && isUnet) {
            if (isFluxModel(selectedCheckpoint)) effectiveVae = "ae.safetensors";
            else if (isAuraFlowModel(selectedCheckpoint) || isPonyModel(selectedCheckpoint)) effectiveVae = "sdxl_vae.safetensors";
        }

        const options = {
            mode: 't2i',
            prompt, negativePrompt, seed: jobSeed, steps, cfg, sampler, scheduler,
            width, height, batchSize,
            checkpoint: isUnet ? null : selectedCheckpoint?.name,
            unet: isUnet ? selectedCheckpoint?.name : null,
            clip: isUnet ? selectedClip : null,
            clip2: (isUnet && isFluxModel(selectedCheckpoint)) ? selectedClip2 : null,
            vae: effectiveVae,
            loras: selectedLoras, controlnets, ipAdapters,
            hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps,
            adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise, adetailerInpaintMasked,
            clipSkip, enableFreeU, enablePAG, pagScale,
            enableLatentUpscale, latentUpscaleMultiplier,
            modelType: isFluxModel(selectedCheckpoint) ? 'flux' : (isPonyModel(selectedCheckpoint) || isAuraFlowModel(selectedCheckpoint)) ? 'sdxl' : 'sd15'
        };

        const metadata = {
            prompt, negativePrompt, seed: jobSeed, steps, cfg, sampler, scheduler,
            width, height, batchSize,
            checkpoint: selectedCheckpoint, vae: selectedVae, loras: selectedLoras,
            embeddings: extractEmbeddingsFromPrompt(prompt, negativePrompt),
            hiresFix, hiresUpscaler, adetailer, adetailerModel,
            clipSkip, enableFreeU, enablePAG, pagScale, enableLatentUpscale,
            ipAdapters, controlnets
        };

        return { options, metadata };
    };

    const runSubmission = async () => {
        const { options, metadata } = buildSimpleWorkflowPayload();
        return runWithPreflight(options, {
            onValid: async () => generateApi.workflow(options, metadata, {
                idempotencyKey: createIdempotencyKey('generate-simple')
            }),
        });
    };

    const {
        progress,
        generating,
        setGenerating,
        handleGenerate,
    } = useGeneratorJob({
        runSubmission,
        type: 'simple',
        setGeneratingOnQueue: false,
        randomizeSeed,
        autoRandomizeSeed,
    });

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

            const validation = await runWithPreflight(payloads[0]?.options);
            if (!validation.ok) return;

            const jobs = payloads.map(({ options, metadata, index }) => (
                generateApi.workflow(options, metadata, {
                    idempotencyKey: createIdempotencyKey(`generate-variation-${index}`)
                })
            ));

            await Promise.all(jobs);
            toast.success(`Queued ${count} variations!`, { icon: '🎲' });
            if (autoRandomizeSeed) randomizeSeed();
            navigate('/gallery');
        } catch (e) {
            toast.error("Error: " + e.message);
        } finally {
            setGenerating(false);
        }
    };

    return (
        <UnifiedGeneratorLayout
            mode="t2i"
            accentClass="from-blue-400 to-purple-500"
            runwayTitle="Generation Runway"
            runwayHint="Provider health and model checks before you commit a generation."
            rightColumnMiddle={<ResolutionSettings />}
            rightColumnBottom={
                <GenerateButtonBar
                    generating={generating}
                    progress={progress}
                    prompt={prompt}
                    onGenerate={() => handleGenerate({ shouldRedirect: true, trackQueuedJob: true })}
                    onQueue={() => handleGenerate({ shouldRedirect: false, trackQueuedJob: false })}
                    onGenerateVariations={handleGenerateVariations}
                />
            }
        />
    );
}
