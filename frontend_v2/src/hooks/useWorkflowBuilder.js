import { useGeneratorCore } from './useGeneratorCore';
import { generateApi, createIdempotencyKey } from '../api';
import { isUnetModel, isFluxModel, isAuraFlowModel, isPonyModel, resolveModelType } from '../utils/modelType';
import { useSettings } from '../store/settingsStore';
import { lorasFromSelectedLoras, lorasToRequestOptions } from './useBatchPresets';

export function useWorkflowBuilder(mode) {
    const { store, preflight: { runWithPreflight } } = useGeneratorCore();
    const settings = useSettings();
    const promptShortcuts = (settings.generator?.prompt_shortcuts) || {};
    const shortcutNames = Object.keys(promptShortcuts);

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

    const extractShortcutsFromPrompt = (positivePrompt, negativePrompt) => {
        const positive = [];
        const negative = [];
        shortcutNames.forEach((name) => {
            if (positivePrompt.includes(name)) positive.push(name);
            if (negativePrompt.includes(name)) negative.push(name);
        });
        return { positive, negative };
    };

    const buildPayload = (jobSeed, additionalOverrides = {}) => {
        // The overrides MERGE over the store's values, rather than being a
        // fixed set of extra keys. The Batch page supplies its own prompt
        // for each entry, and the inpaint page supplies the mask and the
        // model to use for the inpaint pass - so an override has to be able
        // to replace a value, not only add one.
        const {
            prompt, negativePrompt, seed, steps, cfg, sampler, scheduler, width, height, batchSize,
            selectedCheckpoint, selectedVae, selectedClip, selectedClip2, selectedLoras, controlnets,
            hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps,
            adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise, adetailerInpaintMasked,
            clipSkip, enableFreeU, enablePAG, pagScale,
            enableLatentUpscale, latentUpscaleMultiplier,
            ipAdapters, sourceImage, denoise, maskBlur,
            growMask,
        } = { ...store, ...additionalOverrides };

        const actualSeed = jobSeed !== undefined ? jobSeed : seed;

        // The loras are narrowed to the backend's LoraOption shape on
        // purpose. `selectedLoras` carries preview images and CivitAI
        // metadata, which Pydantic drops - but the body still carries them,
        // and a batch multiplies that across every entry. The METADATA
        // keeps the records, because "Reuse parameters" restores from it.
        const requestLoras = lorasToRequestOptions(lorasFromSelectedLoras(selectedLoras));

        // The model, and the loader it needs.
        //
        // The backend chooses the loader from `unet` + `clip`, NOT from the
        // mode, so these fields belong in EVERY mode. They used to be sent
        // only for t2i, which meant a UNET model selected in img2img mode
        // was sent as `checkpoint` - and a UNET lives in models/unet/, not
        // models/checkpoints/, so no provider had it and the request failed
        // with "Missing Models" for a model the user had installed.
        const isUnet = isUnetModel(selectedCheckpoint);
        let effectiveVae = selectedVae;
        if (effectiveVae === "Baked in" && isUnet) {
            if (isFluxModel(selectedCheckpoint)) effectiveVae = "ae.safetensors";
            else if (isAuraFlowModel(selectedCheckpoint) || isPonyModel(selectedCheckpoint)) effectiveVae = "sdxl_vae.safetensors";
        }

        const modelOptions = {
            checkpoint: isUnet ? null : selectedCheckpoint?.name,
            unet: isUnet ? selectedCheckpoint?.name : null,
            clip: isUnet ? selectedClip : null,
            clip2: (isUnet && isFluxModel(selectedCheckpoint)) ? selectedClip2 : null,
            vae: effectiveVae,
            modelType: resolveModelType(selectedCheckpoint),
        };

        // Base options shared across all modes
        let options = {
            mode,
            prompt, negativePrompt, seed: actualSeed, steps, cfg, sampler, scheduler,
            loras: requestLoras, controlnets, ipAdapters,
            clipSkip, enableFreeU, enablePAG, pagScale,
            enableLatentUpscale, latentUpscaleMultiplier,
            adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise, adetailerInpaintMasked,
            ...modelOptions,
        };

        let metadata = {
            type: mode,
            prompt, negativePrompt, seed: actualSeed, steps, cfg, sampler, scheduler,
            loras: selectedLoras, controlnets, ipAdapters,
            clipSkip, enableFreeU, enablePAG, pagScale,
            enableLatentUpscale,
            adetailer, adetailerModel,
            // The model RECORD, not its name: the gallery shows the record's
            // display name and its visual fields. The backend's own
            // graph-derived metadata carries the name, because the backend
            // does not know the record - so the readers of this field accept
            // both shapes.
            checkpoint: selectedCheckpoint,
            vae: selectedVae,
        };

        if (mode === 't2i') {
            options = {
                ...options,
                width, height, batchSize,
                hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps,
            };
            metadata = {
                ...metadata,
                width, height, batchSize,
                embeddings: extractEmbeddingsFromPrompt(prompt, negativePrompt),
                shortcuts: extractShortcutsFromPrompt(prompt, negativePrompt),
                hiresFix, hiresUpscaler
            };
        } else if (mode === 'img2img') {
            options = {
                ...options,
                inputImage: sourceImage?.filename,
                denoise,
            };
            metadata = {
                ...metadata,
                denoise,
                width: sourceImage?.width,
                height: sourceImage?.height,
                sourceImage: sourceImage?.filename,
            };
        } else if (mode === 'inpaint') {
            options = {
                ...options,
                inputImage: sourceImage?.filename,
                maskImage: additionalOverrides.maskResult?.filename,
                denoise,
                // The inpaint pass can use a different model from the one the
                // page has selected. Only then does it override the model
                // fields; otherwise they stand.
                ...(additionalOverrides.checkpointToUse
                    ? { checkpoint: additionalOverrides.checkpointToUse, unet: null, clip: null, clip2: null }
                    : {}),
                maskBlur,
                growMask: growMask ?? 6,
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
