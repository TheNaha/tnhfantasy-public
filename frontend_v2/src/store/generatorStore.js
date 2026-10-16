/**
 * generatorStore.js - Image generation parameter store (persisted)
 *
 * Manages all user-facing generation settings and provides actions to mutate
 * them.  The store is persisted to localStorage via Zustand's `persist`
 * middleware so settings survive page refreshes.
 *
 * STATE GROUPS:
 *   Generation params  – prompt, negativePrompt, seed, steps, cfg, sampler,
 *                        scheduler, width, height, batchSize
 *   Models             – selectedCheckpoint, selectedVae, selectedClip,
 *                        selectedClip2, selectedLoras[], controlnets[]
 *   Enhancements       – hiresFix settings, adetailer settings
 *   Img2Img / Inpaint  - sourceImage, denoise, maskImage, maskBlur
 *   Presets            - savedPresets[] (parameter bundles, local only)
 *
 * AUTO-APPLY:
 *   When a checkpoint is selected and `autoApplyModelSettings` is true, the
 *   store detects the base model type (illustrious, pony, sdxl, sd15, flux,
 *   sd3) from the checkpoint metadata and applies the community-recommended
 *   default settings for that architecture automatically.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/**
 * Community-recommended default generation settings per base model type.
 * These are applied automatically when `autoApplyModelSettings` is enabled.
 */
const BASE_MODEL_SETTINGS = {
    illustrious: {
        steps: 25, cfg: 6.0, sampler: 'euler_ancestral', scheduler: 'normal',
        width: 1024, height: 1024, clipSkip: 2
    },
    pony: {
        steps: 25, cfg: 6.0, sampler: 'dpmpp_2m', scheduler: 'karras',
        width: 1024, height: 1024, clipSkip: 2
    },
    sdxl: {
        steps: 30, cfg: 7.0, sampler: 'dpmpp_2m', scheduler: 'karras',
        width: 1024, height: 1024, clipSkip: 1
    },
    sd15: {
        steps: 25, cfg: 7.0, sampler: 'euler_ancestral', scheduler: 'normal',
        width: 512, height: 768, clipSkip: 1
    },
    flux: {
        steps: 20, cfg: 1.0, sampler: 'euler', scheduler: 'normal',
        width: 1024, height: 1024
    },
    sd3: {
        steps: 28, cfg: 4.5, sampler: 'dpmpp_2m', scheduler: 'sgm_uniform',
        width: 1024, height: 1024
    }
};

/**
 * Detect base model type from checkpoint (works with V1 and V2 formats)
 */
function detectBaseModel(checkpoint) {
    if (!checkpoint) return null;

    let baseModel = null;

    // V2 format: base_model at root level
    if (checkpoint.base_model) {
        baseModel = checkpoint.base_model;
    }
    // V1 format: nested in metadata
    else if (checkpoint.metadata?.baseModel) {
        baseModel = checkpoint.metadata.baseModel;
    }
    // V1 format: nested in modelVersions (CivitAI API response)
    else if (checkpoint.metadata?.modelVersions?.[0]?.baseModel) {
        baseModel = checkpoint.metadata.modelVersions[0].baseModel;
    }

    // Check name for hints if no direct field
    if (!baseModel) {
        const name = (checkpoint.name || checkpoint.display_name || '').toLowerCase();
        if (name.includes('flux')) return 'flux';
        if (name.includes('sd3') || name.includes('sd 3')) return 'sd3';
        if (name.includes('illustrious') || name.includes('ill-') || name.includes('illu')) return 'illustrious';
        if (name.includes('pony')) return 'pony';
        if (name.includes('sdxl') || name.includes('xl')) return 'sdxl';
        if (name.includes('sd1.5') || name.includes('sd 1.5') || name.includes('sd15')) return 'sd15';
        return null;
    }

    const baseModelLower = baseModel.toLowerCase();
    if (baseModelLower.includes('illustrious')) return 'illustrious';
    if (baseModelLower.includes('pony')) return 'pony';
    if (baseModelLower.includes('flux')) return 'flux';
    if (baseModelLower.includes('sd 3') || baseModelLower.includes('sd3')) return 'sd3';
    if (baseModelLower.includes('sdxl') || baseModelLower.includes('xl')) return 'sdxl';
    if (baseModelLower.includes('sd 1') || baseModelLower.includes('1.5')) return 'sd15';

    return null;
}

export const useGeneratorStore = create(
    persist(
        (set, get) => ({
            // Generation Parameters
            prompt: "A beautiful landscape, 8k, highly detailed",
            negativePrompt: "blur, low quality, watermark",
            seed: Math.floor(Math.random() * Number.MAX_SAFE_INTEGER),
            steps: 25,
            cfg: 7.0,
            sampler: "euler",
            scheduler: "normal",
            clipSkip: 1,
            enableFreeU: false,
            enablePAG: false,
            pagScale: 3.0,
            enableLatentUpscale: false,
            latentUpscaleMultiplier: 1.5,
            width: 1024,
            height: 1024,
            batchSize: 1,
            aspectRatioLocked: false,
            lockedParams: {
                width: false,
                height: false,
                batchSize: false,
                steps: false,
                cfg: false,
                sampler: false,
                scheduler: false,
                clipSkip: false,
            },
            controlnets: [],
            ipAdapters: [],
            preflightTick: 0,
            // Preflight dialog state lives here, not in useState inside
            // useGenerationPreflight. useGeneratorCore() is called
            // independently in five places and each call used to get its own
            // private copy, so the instance whose runWithPreflight() set
            // "missing models" was never the instance whose
            // isMissingModelsOpen the modal read — the dialog could never open.
            // isChecking must also be shared, for the same reason.
            preflightChecking: false,
            isMissingModelsOpen: false,

            // Models
            selectedCheckpoint: null,
            selectedVae: "Baked in",
            selectedClip: null,      // For Flux: T5XXL model
            selectedClip2: null,     // For Flux: CLIP-L model
            selectedLoras: [], // Array of { name, strength, metadata, preview }

            // Enhancements
            hiresFix: false,
            hiresUpscaler: "Latent",
            hiresDenoise: 0.5,
            hiresUpscale: 1.5,
            hiresSteps: 10,

            adetailer: false,
            adetailerModel: "face_yolov8n.pt",
            adetailerPrompt: "",
            adetailerSteps: 20,
            adetailerDenoise: 0.4,
            adetailerInpaintMasked: true,

            // Auto-apply model settings toggle
            autoApplyModelSettings: true,

            // Img2Img & Inpainting State
            sourceImage: null,    // { filename, path, previewUrl, width, height, needsSync }
            denoise: 0.7,         // Denoise strength for Img2Img/Inpaint (0.0-1.0)
            maskImage: null,      // Base64 data URL of the mask for inpainting
            maskBlur: 4,          // Blur mask edges (0-20 pixels)



            // Saved Presets (Parameters only)
            savedPresets: [
                {
                    id: 'sdxl-quality',
                    name: 'SDXL High Quality',
                    description: 'Optimal settings for SDXL models',
                    data: { steps: 30, cfg: 7.0, sampler: 'dpmpp_2m', scheduler: 'karras', width: 1024, height: 1024 }
                },
                {
                    id: 'sd15-portrait',
                    name: 'SD1.5 Portrait',
                    description: 'Standard portrait settings for SD1.5',
                    data: { steps: 20, cfg: 7.0, sampler: 'euler_ancestral', scheduler: 'normal', width: 512, height: 768 }
                },
                {
                    id: 'fast-preview',
                    name: 'Fast Preview',
                    description: 'Low steps for quick iteration',
                    data: { steps: 12, cfg: 4.0, sampler: 'dpmpp_sde', scheduler: 'karras', width: 512, height: 512 }
                }
            ],

            // Actions
            toggleParamLock: (paramName) => set((state) => ({
                lockedParams: {
                    ...state.lockedParams,
                    [paramName]: !state.lockedParams[paramName]
                }
            })),
            setPrompt: (prompt) => set((state) => ({ prompt, preflightTick: state.preflightTick + 1 })),
            setNegativePrompt: (negativePrompt) => set((state) => ({ negativePrompt, preflightTick: state.preflightTick + 1 })),
            setSeed: (seed) => set((state) => ({ seed, preflightTick: state.preflightTick + 1 })),
            setSteps: (steps) => set((state) => ({ steps, preflightTick: state.preflightTick + 1 })),
            setCfg: (cfg) => set((state) => ({ cfg, preflightTick: state.preflightTick + 1 })),
            setSampler: (sampler) => set((state) => ({ sampler, preflightTick: state.preflightTick + 1 })),
            setScheduler: (scheduler) => set((state) => ({ scheduler, preflightTick: state.preflightTick + 1 })),
            setClipSkip: (clipSkip) => set((state) => ({ clipSkip, preflightTick: state.preflightTick + 1 })),
            setEnableFreeU: (enableFreeU) => set((state) => ({ enableFreeU, preflightTick: state.preflightTick + 1 })),
            setEnablePAG: (enablePAG) => set((state) => ({ enablePAG, preflightTick: state.preflightTick + 1 })),
            setPagScale: (pagScale) => set((state) => ({ pagScale, preflightTick: state.preflightTick + 1 })),
            setEnableLatentUpscale: (enableLatentUpscale) => set((state) => ({ enableLatentUpscale, preflightTick: state.preflightTick + 1 })),
            setLatentUpscaleMultiplier: (latentUpscaleMultiplier) => set((state) => ({ latentUpscaleMultiplier, preflightTick: state.preflightTick + 1 })),
            setWidth: (width) => set((state) => ({ width, preflightTick: state.preflightTick + 1 })),
            setHeight: (height) => set((state) => ({ height, preflightTick: state.preflightTick + 1 })),
            setBatchSize: (batchSize) => set((state) => ({ batchSize, preflightTick: state.preflightTick + 1 })),
            setAspectRatioLocked: (aspectRatioLocked) => set((state) => ({ aspectRatioLocked, preflightTick: state.preflightTick + 1 })),
            setAutoApplyModelSettings: (autoApplyModelSettings) => set((state) => ({ autoApplyModelSettings, preflightTick: state.preflightTick + 1 })),

            // Enhanced checkpoint selection with auto-apply
            setSelectedCheckpoint: (checkpoint) => {
                const state = get();
                const newState = { selectedCheckpoint: checkpoint, preflightTick: state.preflightTick + 1 };

                // Auto-apply settings if enabled and checkpoint has metadata
                if (state.autoApplyModelSettings && checkpoint) {
                    const modelType = detectBaseModel(checkpoint);

                    if (modelType && BASE_MODEL_SETTINGS[modelType]) {
                        const settings = BASE_MODEL_SETTINGS[modelType];
                        const locked = state.lockedParams || {};
                        for (const [key, value] of Object.entries(settings)) {
                            if (!locked[key]) {
                                newState[key] = value;
                            }
                        }
                    }
                }

                set(newState);
            },

            setSelectedVae: (selectedVae) => set((state) => ({ selectedVae, preflightTick: state.preflightTick + 1 })),
            setSelectedClip: (selectedClip) => set((state) => ({ selectedClip, preflightTick: state.preflightTick + 1 })),
            setSelectedClip2: (selectedClip2) => set((state) => ({ selectedClip2, preflightTick: state.preflightTick + 1 })),
            setSelectedLoras: (selectedLoras) => set((state) => ({ selectedLoras, preflightTick: state.preflightTick + 1 })),

            setHiresFix: (hiresFix) => set({ hiresFix }),
            setPreflightChecking: (preflightChecking) => set({ preflightChecking }),
            setIsMissingModelsOpen: (isMissingModelsOpen) => set({ isMissingModelsOpen }),
            setHiresUpscaler: (hiresUpscaler) => set({ hiresUpscaler }),
            setHiresDenoise: (hiresDenoise) => set({ hiresDenoise }),
            setHiresUpscale: (hiresUpscale) => set({ hiresUpscale }),
            setHiresSteps: (hiresSteps) => set({ hiresSteps }),

            setAdetailer: (adetailer) => set({ adetailer }),
            setAdetailerModel: (adetailerModel) => set({ adetailerModel }),
            setAdetailerPrompt: (adetailerPrompt) => set({ adetailerPrompt }),
            setAdetailerSteps: (adetailerSteps) => set({ adetailerSteps }),
            setAdetailerDenoise: (adetailerDenoise) => set({ adetailerDenoise }),
            setAdetailerInpaintMasked: (adetailerInpaintMasked) => set({ adetailerInpaintMasked }),

            // Img2Img & Inpainting Actions
            setSourceImage: (sourceImage) => set({ sourceImage }),
            setDenoise: (denoise) => set({ denoise }),
            setMaskImage: (maskImage) => set({ maskImage }),
            setMaskBlur: (maskBlur) => set({ maskBlur }),
            clearSourceImage: () => set({ sourceImage: null, maskImage: null }),



            addPreset: (preset) => set((state) => ({
                savedPresets: [...state.savedPresets, { ...preset, id: Date.now().toString() }]
            })),

            removePreset: (id) => set((state) => ({
                savedPresets: state.savedPresets.filter(p => p.id !== id)
            })),

            // Helper Actions
            randomizeSeed: () => set({ seed: Math.floor(Math.random() * Number.MAX_SAFE_INTEGER) }),

            addLora: () => set((state) => ({
                selectedLoras: [...state.selectedLoras, { name: "", strength: 1.0 }], preflightTick: state.preflightTick + 1
            })),

            removeLora: (index) => set((state) => {
                const newLoras = [...state.selectedLoras];
                newLoras.splice(index, 1);
                return { selectedLoras: newLoras, preflightTick: state.preflightTick + 1 };
            }),

            updateLora: (index, field, value) => set((state) => {
                const newLoras = [...state.selectedLoras];
                if (field === 'model') {
                    // V2 format: spread all model properties directly
                    // Preserve strength from existing lora, override everything else
                    const currentStrength = newLoras[index].strength || 1.0;
                    newLoras[index] = {
                        ...value,  // Copy all model properties (name, display_name, preview, trained_words, base_model, etc.)
                        strength: currentStrength
                    };
                } else {
                    newLoras[index][field] = value;
                }
                return { selectedLoras: newLoras, preflightTick: state.preflightTick + 1 };
            }),

            addControlNet: (defaultModelName) => set((state) => ({
                controlnets: [...state.controlnets, { name: defaultModelName || "", image: "", strength: 1.0, preprocessor: "None" }]
            })),

            removeControlNet: (index) => set((state) => {
                const newCns = [...state.controlnets];
                newCns.splice(index, 1);
                return { controlnets: newCns };
            }),

            updateControlNet: (index, field, value) => set((state) => ({
                controlnets: state.controlnets.map((cn, i) => i === index ? { ...cn, [field]: value } : cn),
                preflightTick: state.preflightTick + 1
            })),
            addIpAdapter: () => set((state) => ({ 
                ipAdapters: [...state.ipAdapters, { image: null, model: '', clipVision: '', weight: 1.0, stopAt: 1.0 }],
                preflightTick: state.preflightTick + 1
            })),
            removeIpAdapter: (index) => set((state) => ({ 
                ipAdapters: state.ipAdapters.filter((_, i) => i !== index),
                preflightTick: state.preflightTick + 1
            })),
            updateIpAdapter: (index, field, value) => set((state) => ({
                ipAdapters: state.ipAdapters.map((ip, i) => i === index ? { ...ip, [field]: value } : ip),
                preflightTick: state.preflightTick + 1
            })),

            addTriggerWords: (words) => set((state) => {
                if (!words) return {};
                const currentPrompt = typeof state.prompt === 'string' ? state.prompt : '';
                const toAdd = words.filter(w => !currentPrompt.includes(w));
                if (toAdd.length === 0) return {};
                return { prompt: currentPrompt + (currentPrompt ? ", " : "") + toAdd.join(", ") };
            }),

            // Bulk Set (for loading saved prompts / reusing parameters).
            // Locked parameters are never overwritten — a lock means "do not
            // change this value", which applies to every bulk writer, including
            // the "Reuse Parameters" button.
            setAll: (newState) => set((state) => {
                const locked = state.lockedParams || {};
                const filtered = {};
                for (const [key, value] of Object.entries(newState || {})) {
                    if (!locked[key]) {
                        filtered[key] = value;
                    }
                }
                return { ...state, ...filtered };
            })
        }),
        {
            name: 'generator-storage', // name of the item in the storage (must be unique)
            partialize: (state) => {
                const {
                    sourceImage,
                    maskImage,
                    preflightTick,
                    preflightChecking,
                    isMissingModelsOpen,
                    // `ipAdapters` was in `rest`, so it was persisted verbatim —
                    // and each entry's `image` is a `blob:` URL from
                    // `URL.createObjectURL(file)` in `ImageUploader.jsx`. Those
                    // URLs are scoped to the document that created them and are
                    // dead the moment the tab reloads, but the persisted entry
                    // stays truthy. On restore, `ImageUploader` saw a non-null
                    // image and rendered `<img src="blob:http://…">`, which
                    // displays a broken image: the dropzone behind it was
                    // unreachable and only the clear button escaped.
                    //
                    // The settings are worth keeping — re-picking a reference
                    // image should not mean re-typing its weight and clip model
                    // — so they are kept and the blob-bearing field is dropped.
                    ipAdapters,
                    ...rest
                } = state;
                return {
                    ...rest,
                    ipAdapters: (ipAdapters || []).map(({ image, ...settings }) => ({
                        ...settings,
                        image: null,
                    })),
                };
            }
        }
    )
);
