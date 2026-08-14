import { useGeneratorCore } from './useGeneratorCore';
import { generateApi, createIdempotencyKey } from '../api';
import { isUnetModel, isFluxModel, isAuraFlowModel, isPonyModel } from '../utils/modelType';

export function useWorkflowBuilder(mode) {
    const { store, preflight: { runWithPreflight } } = useGeneratorCore();

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

    const buildPayload = (jobSeed, additionalOverrides = {}) => {
        const {
            prompt, negativePrompt, seed, steps, cfg, sampler, scheduler, width, height, batchSize,
            selectedCheckpoint, selectedVae, selectedClip, selectedClip2, selectedLoras, controlnets,
            hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps,
            adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise, adetailerInpaintMasked,
            clipSkip, enableFreeU, enablePAG, pagScale,
            enableLatentUpscale, latentUpscaleMultiplier,
            ipAdapters, sourceImage, denoise, maskBlur,
        } = store;

        const actualSeed = jobSeed !== undefined ? jobSeed : seed;

        // Base options shared across all modes
        let options = {
            mode,
            prompt, negativePrompt, seed: actualSeed, steps, cfg, sampler, scheduler,
            loras: selectedLoras, controlnets, ipAdapters,
            clipSkip, enableFreeU, enablePAG, pagScale,
            enableLatentUpscale, latentUpscaleMultiplier,
            adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise, adetailerInpaintMasked,
        };

        let metadata = {
            type: mode,
            prompt, negativePrompt, seed: actualSeed, steps, cfg, sampler, scheduler,
            loras: selectedLoras, controlnets, ipAdapters,
            clipSkip, enableFreeU, enablePAG, pagScale,
            enableLatentUpscale,
            adetailer, adetailerModel
        };

        const isUnet = mode === 't2i' && isUnetModel(selectedCheckpoint);
        let effectiveVae = selectedVae;
        
        if (mode === 't2i') {
            if (effectiveVae === "Baked in" && isUnet) {
                if (isFluxModel(selectedCheckpoint)) effectiveVae = "ae.safetensors";
                else if (isAuraFlowModel(selectedCheckpoint) || isPonyModel(selectedCheckpoint)) effectiveVae = "sdxl_vae.safetensors";
            }
            options = {
                ...options,
                width, height, batchSize,
                checkpoint: isUnet ? null : selectedCheckpoint?.name,
                unet: isUnet ? selectedCheckpoint?.name : null,
                clip: isUnet ? selectedClip : null,
                clip2: (isUnet && isFluxModel(selectedCheckpoint)) ? selectedClip2 : null,
                vae: effectiveVae,
                hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps,
                modelType: isFluxModel(selectedCheckpoint) ? 'flux' : (isPonyModel(selectedCheckpoint) || isAuraFlowModel(selectedCheckpoint)) ? 'sdxl' : 'sd15'
            };
            metadata = {
                ...metadata,
                width, height, batchSize,
                checkpoint: selectedCheckpoint, vae: selectedVae,
                embeddings: extractEmbeddingsFromPrompt(prompt, negativePrompt),
                hiresFix, hiresUpscaler
            };
        } else if (mode === 'img2img') {
            options = {
                ...options,
                inputImage: sourceImage?.filename,
                denoise,
                checkpoint: selectedCheckpoint?.name,
                vae: selectedVae,
            };
            metadata = {
                ...metadata,
                denoise,
                width: sourceImage?.width,
                height: sourceImage?.height,
                sourceImage: sourceImage?.filename,
                checkpoint: selectedCheckpoint,
                vae: selectedVae,
            };
        } else if (mode === 'inpaint') {
            options = {
                ...options,
                inputImage: sourceImage?.filename,
                maskImage: additionalOverrides.maskResult?.filename,
                denoise,
                checkpoint: additionalOverrides.checkpointToUse || selectedCheckpoint?.name,
                vae: selectedVae,
                maskBlur,
                growMask: 6,
            };
            metadata = {
                ...metadata,
                denoise,
                maskBlur,
                width: sourceImage?.width,
                height: sourceImage?.height,
                sourceImage: sourceImage?.filename,
                maskImage: additionalOverrides.maskResult?.filename,
                checkpoint: additionalOverrides.inpaintCheckpoint || selectedCheckpoint,
                vae: selectedVae,
                usedInpaintModel: !!additionalOverrides.inpaintCheckpoint
            };
        }

        return { options, metadata };
    };

    const runSubmission = async (additionalOverrides = {}) => {
        const { options, metadata } = buildPayload(undefined, additionalOverrides);
        const idKey = mode === 't2i' ? 'generate-simple' : `generate-${mode}`;
        return runWithPreflight(options, {
            onValid: async () => generateApi.workflow(options, metadata, {
                idempotencyKey: createIdempotencyKey(idKey)
            }),
        });
    };

    return {
        buildPayload,
        runSubmission,
        runWithPreflight
    };
}
