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
 *   Img2Img / Inpaint  – sourceImage, denoise, maskImage, maskBlur
 *   Saved prompts      – savedPrompts[] (synced from server via promptStore)
 *   Presets            – savedPresets[] (parameter bundles, local only)
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
        width: 1024, height: 1024
    },
    pony: {
        steps: 25, cfg: 6.0, sampler: 'dpmpp_2m', scheduler: 'karras',
        width: 1024, height: 1024
    },
    sdxl: {
        steps: 30, cfg: 7.0, sampler: 'dpmpp_2m', scheduler: 'karras',
        width: 1024, height: 1024
    },
    sd15: {
        steps: 25, cfg: 7.0, sampler: 'euler_ancestral', scheduler: 'normal',
        width: 512, height: 768
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
            width: 1024,
            height: 1024,
            batchSize: 1,
            aspectRatioLocked: false,

            // Models
            selectedCheckpoint: null,
            selectedVae: "Baked in",
            selectedClip: null,      // For Flux: T5XXL model
            selectedClip2: null,     // For Flux: CLIP-L model
            selectedLoras: [], // Array of { name, strength, metadata, preview }
            controlnets: [], // Array of { name, image, strength, preprocessor }

            // Enhancements
            hiresFix: false,
            hiresUpscaler: "Latent",
            hiresDenoise: 0.5,
            hiresUpscale: 1.5,
            hiresSteps: 10,

            adetailer: false,
            adetailerModel: "face_yolov8n.pt",
            adetailerPrompt: "",
            adetailerNegative: "",
            adetailerSteps: 20,
            adetailerDenoise: 0.4,
            adetailerInpaintMasked: true,

            // Auto-apply model settings toggle
            autoApplyModelSettings: true,
            lastAppliedModelType: null,

            // Img2Img & Inpainting State
            sourceImage: null,    // { filename, path, previewUrl, width, height, needsSync }
            denoise: 0.7,         // Denoise strength for Img2Img/Inpaint (0.0-1.0)
            maskImage: null,      // Base64 data URL of the mask for inpainting
            maskBlur: 4,          // Blur mask edges (0-20 pixels)

            // Saved Prompts
            savedPrompts: [],

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
            setPrompt: (prompt) => set({ prompt }),
            setNegativePrompt: (negativePrompt) => set({ negativePrompt }),
            setSeed: (seed) => set({ seed }),
            setSteps: (steps) => set({ steps }),
            setCfg: (cfg) => set({ cfg }),
            setSampler: (sampler) => set({ sampler }),
            setScheduler: (scheduler) => set({ scheduler }),
            setWidth: (width) => set({ width }),
            setHeight: (height) => set({ height }),
            setBatchSize: (batchSize) => set({ batchSize }),
            setAspectRatioLocked: (aspectRatioLocked) => set({ aspectRatioLocked }),
            setAutoApplyModelSettings: (autoApplyModelSettings) => set({ autoApplyModelSettings }),

            // Enhanced checkpoint selection with auto-apply
            setSelectedCheckpoint: (checkpoint) => {
                const state = get();
                const newState = { selectedCheckpoint: checkpoint };

                // Auto-apply settings if enabled and checkpoint has metadata
                if (state.autoApplyModelSettings && checkpoint) {
                    const modelType = detectBaseModel(checkpoint);

                    if (modelType && BASE_MODEL_SETTINGS[modelType]) {
                        const settings = BASE_MODEL_SETTINGS[modelType];
                        Object.assign(newState, settings);
                        newState.lastAppliedModelType = modelType;
                        console.log(`[Generator] Auto-applied ${modelType} settings`);
                    }
                }

                set(newState);
            },

            setSelectedVae: (selectedVae) => set({ selectedVae }),
            setSelectedClip: (selectedClip) => set({ selectedClip }),
            setSelectedClip2: (selectedClip2) => set({ selectedClip2 }),
            setSelectedLoras: (selectedLoras) => set({ selectedLoras }),
            setControlnets: (controlnets) => set({ controlnets }),

            setHiresFix: (hiresFix) => set({ hiresFix }),
            setHiresUpscaler: (hiresUpscaler) => set({ hiresUpscaler }),
            setHiresDenoise: (hiresDenoise) => set({ hiresDenoise }),
            setHiresUpscale: (hiresUpscale) => set({ hiresUpscale }),
            setHiresSteps: (hiresSteps) => set({ hiresSteps }),

            setAdetailer: (adetailer) => set({ adetailer }),
            setAdetailerModel: (adetailerModel) => set({ adetailerModel }),
            setAdetailerPrompt: (adetailerPrompt) => set({ adetailerPrompt }),
            setAdetailerNegative: (adetailerNegative) => set({ adetailerNegative }),
            setAdetailerSteps: (adetailerSteps) => set({ adetailerSteps }),
            setAdetailerDenoise: (adetailerDenoise) => set({ adetailerDenoise }),
            setAdetailerInpaintMasked: (adetailerInpaintMasked) => set({ adetailerInpaintMasked }),

            // Img2Img & Inpainting Actions
            setSourceImage: (sourceImage) => set({ sourceImage }),
            setDenoise: (denoise) => set({ denoise }),
            setMaskImage: (maskImage) => set({ maskImage }),
            setMaskBlur: (maskBlur) => set({ maskBlur }),
            clearSourceImage: () => set({ sourceImage: null, maskImage: null }),
            clearMask: () => set({ maskImage: null }),

            setSavedPrompts: (savedPrompts) => set({ savedPrompts }),

            addPreset: (preset) => set((state) => ({
                savedPresets: [...state.savedPresets, { ...preset, id: Date.now().toString() }]
            })),

            removePreset: (id) => set((state) => ({
                savedPresets: state.savedPresets.filter(p => p.id !== id)
            })),

            // Helper Actions
            randomizeSeed: () => set({ seed: Math.floor(Math.random() * Number.MAX_SAFE_INTEGER) }),

            addLora: () => set((state) => ({
                selectedLoras: [...state.selectedLoras, { name: "", strength: 1.0 }]
            })),

            removeLora: (index) => set((state) => {
                const newLoras = [...state.selectedLoras];
                newLoras.splice(index, 1);
                return { selectedLoras: newLoras };
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
                return { selectedLoras: newLoras };
            }),

            addControlNet: (defaultModelName) => set((state) => ({
                controlnets: [...state.controlnets, { name: defaultModelName || "", image: "", strength: 1.0, preprocessor: "None" }]
            })),

            removeControlNet: (index) => set((state) => {
                const newCns = [...state.controlnets];
                newCns.splice(index, 1);
                return { controlnets: newCns };
            }),

            updateControlNet: (index, field, value) => set((state) => {
                const newCns = [...state.controlnets];
                newCns[index][field] = value;
                return { controlnets: newCns };
            }),

            addTriggerWords: (words) => set((state) => {
                if (!words) return {};
                const currentPrompt = typeof state.prompt === 'string' ? state.prompt : '';
                const toAdd = words.filter(w => !currentPrompt.includes(w));
                if (toAdd.length === 0) return {};
                return { prompt: currentPrompt + (currentPrompt ? ", " : "") + toAdd.join(", ") };
            }),

            // Apply settings for a specific model type
            applyModelSettings: (modelType) => {
                const settings = BASE_MODEL_SETTINGS[modelType?.toLowerCase()];
                if (settings) {
                    set({ ...settings, lastAppliedModelType: modelType });
                    return true;
                }
                return false;
            },

            applySDXLSettings: () => set({
                width: 1024,
                height: 1024,
                steps: 30,
                cfg: 7.0,
                sampler: "dpmpp_2m",
                scheduler: "karras",
                lastAppliedModelType: 'sdxl'
            }),

            // Bulk Set (for loading saved prompts)
            setAll: (newState) => set((state) => ({ ...state, ...newState }))
        }),
        {
            name: 'generator-storage', // name of the item in the storage (must be unique)
        }
    )
);
