import { useGeneratorCore } from './useGeneratorCore';
import { generateApi, createIdempotencyKey } from '../api';
import { isUnetModel, isFluxModel, isAuraFlowModel, isPonyModel, resolveModelType } from '../utils/modelType';
import { lorasFromSelectedLoras, lorasToRequestOptions } from './useBatchPresets';
import { GUIDED } from '../api/generate';

/**
 * The model fields of a request.
 *
 * The backend chooses the loader from `unet` + `clip`, NOT from the mode, so
 * these fields belong in EVERY mode. They used to be sent only for t2i, which
 * meant a UNET model selected in img2img mode was sent as `checkpoint` - and a
 * UNET lives in models/unet/, not models/checkpoints/, so no provider had it
 * and the request failed with "Missing Models" for a model the user had
 * installed.
 *
 * There are two ways to say which model a request names:
 *
 *   1. `selectedCheckpoint` - the model RECORD from the catalogue. The
 *      record carries `base_model`, which is what says whether the model is a
 *      UNET (Flux, AuraFlow) and which family it belongs to.
 *   2. `model` - the model fields ALREADY RESOLVED, for a caller that is
 *      rebuilding a request from a job's metadata rather than from the
 *      store. The metadata carries names, not records, so the loader choice
 *      has to be stated: `unet` present means the UNET loader.
 *
 * The second form is what "Quick Remix" uses: it has a job's metadata and no
 * generator store at all.
 */
function resolveModelFields(snapshot) {
    const { selectedCheckpoint, selectedClip, selectedClip2, selectedVae } = snapshot;
    const explicit = snapshot.model && typeof snapshot.model === 'object' ? snapshot.model : null;

    const isUnet = explicit ? Boolean(explicit.unet) : isUnetModel(selectedCheckpoint);
    const fluxFamily = explicit
        ? (explicit.modelType === 'flux' || isFluxModel(selectedCheckpoint))
        : isFluxModel(selectedCheckpoint);

    let effectiveVae = explicit ? (explicit.vae ?? selectedVae) : selectedVae;
    if (effectiveVae === "Baked in" && isUnet) {
        if (fluxFamily) effectiveVae = "ae.safetensors";
        else if (isAuraFlowModel(selectedCheckpoint) || isPonyModel(selectedCheckpoint)) effectiveVae = "sdxl_vae.safetensors";
    }

    if (explicit) {
        return {
            checkpoint: explicit.checkpoint ?? null,
            unet: explicit.unet ?? null,
            clip: explicit.clip ?? null,
            clip2: explicit.clip2 ?? null,
            vae: effectiveVae ?? null,
            modelType: explicit.modelType ?? resolveModelType(selectedCheckpoint),
        };
    }

    return {
        checkpoint: isUnet ? null : selectedCheckpoint?.name,
        unet: isUnet ? selectedCheckpoint?.name : null,
        clip: isUnet ? selectedClip : null,
        clip2: (isUnet && fluxFamily) ? selectedClip2 : null,
        vae: effectiveVae,
        modelType: resolveModelType(selectedCheckpoint),
    };
}

/**
 * The one request builder.
 *
 * It takes the generator store's state (or any snapshot of it), the mode, and
 * the overrides for this particular request, and returns the two things a
 * request needs: the `options` the backend compiles, and the `metadata` the
 * gallery and "Reuse parameters" read.
 *
 * It is a plain function, not a hook, so a component outside the generator
 * pages can use it - the gallery's "Quick Remix" rebuilds a request from a
 * finished job's metadata and has no generator store of its own.
 *
 * @param {string} mode - 't2i' | 'img2img' | 'inpaint'.
 * @param {object} storeSnapshot - The generator store's state.
 * @param {object} [additionalOverrides] - Values that replace the store's for
 *   this request (the Batch page's per-entry prompt, the inpaint page's mask).
 */
export function buildGeneratorPayload(mode, storeSnapshot = {}, additionalOverrides = {}) {
    // The overrides MERGE over the store's values, rather than being a
    // fixed set of extra keys. The Batch page supplies its own prompt
    // for each entry, and the inpaint page supplies the mask and the
    // model to use for the inpaint pass - so an override has to be able
    // to replace a value, not only add one.
    const snapshot = { ...storeSnapshot, ...additionalOverrides };
    const {
        prompt, negativePrompt, seed, steps, cfg, sampler, scheduler, width, height, batchSize,
        selectedCheckpoint, selectedVae, selectedLoras, controlnets,
        hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps,
        adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise, adetailerInpaintMasked,
        clipSkip, enableFreeU, enablePAG, pagScale,
        enableLatentUpscale, latentUpscaleMultiplier,
        ipAdapters, sourceImage, denoise, maskBlur,
        growMask,
    } = snapshot;

    // The loras are narrowed to the backend's LoraOption shape on
    // purpose. `selectedLoras` carries preview images and CivitAI
    // metadata, which Pydantic drops - but the body still carries them,
    // and a batch multiplies that across every entry. The METADATA
    // keeps the records, because "Reuse parameters" restores from it.
    const requestLoras = lorasToRequestOptions(lorasFromSelectedLoras(selectedLoras));

    const modelOptions = resolveModelFields(snapshot);

    // Base options shared across all modes
    let options = {
        mode,
        // The kind of this request, STATED. The API layer used to infer it
        // from the shape of the payload - "an object with a `mode` or a
        // `prompt` key is options" - so a ComfyUI graph in API format, whose
        // top-level key IS `prompt`, was compiled as generator options and
        // rejected by the option schema. The kind travels with the payload
        // it describes, so no caller has to guess and none has to be
        // changed to stop guessing.
        kind: GUIDED,
        prompt, negativePrompt, seed, steps, cfg, sampler, scheduler,
        loras: requestLoras, controlnets, ipAdapters,
        clipSkip, enableFreeU, enablePAG, pagScale,
        enableLatentUpscale, latentUpscaleMultiplier,
        adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise, adetailerInpaintMasked,
        ...modelOptions,
    };

    let metadata = {
        type: mode,
        prompt, negativePrompt, seed, steps, cfg, sampler, scheduler,
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
        // The UNET and its text encoders.
        //
        // The backend loads a UNET with `unet` + `clip` (+ `clip2` for
        // Flux), and the guided metadata carried only `checkpoint` and
        // `vae`. So "Reuse parameters" on a Flux image restored a model
        // with no text encoder, the request failed, and "Quick Remix"
        // asked models/checkpoints/ for a UNET filename.
        unet: modelOptions.unet,
        clip: modelOptions.clip,
        clip2: modelOptions.clip2,
        modelType: modelOptions.modelType,
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
}

export function useWorkflowBuilder(mode) {
    const { store, preflight: { runWithPreflight } } = useGeneratorCore();

    const buildPayload = (jobSeed, additionalOverrides = {}) => {
        const overrides = { ...additionalOverrides };
        if (jobSeed !== undefined) {
            overrides.seed = jobSeed;
        }
        return buildGeneratorPayload(mode, store, overrides);
    };

    const runSubmission = async (additionalOverrides = {}) => {
        const { options, metadata } = buildPayload(undefined, additionalOverrides);
        const idKey = mode === 't2i' ? 'generate-simple' : `generate-${mode}`;
        return runWithPreflight(options, {
            onValid: async () => generateApi.workflow(options, metadata, {
                kind: GUIDED,
                idempotencyKey: createIdempotencyKey(idKey)
            }),
        });
    };

    return {
        buildPayload,
        runSubmission,
        runWithPreflight
    }
}
