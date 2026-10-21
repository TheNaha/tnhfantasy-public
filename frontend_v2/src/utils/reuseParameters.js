import { filesApi } from '../api';
import { useGeneratorStore } from '../store/generatorStore';
import useSettingsStore from '../store/settingsStore';

function hasOwn(obj, key) {
    return Boolean(obj && Object.prototype.hasOwnProperty.call(obj, key));
}

function firstDefined(obj, keys) {
    for (const key of keys) {
        if (hasOwn(obj, key) && obj[key] !== undefined && obj[key] !== null) {
            return obj[key];
        }
    }
    return undefined;
}

function toFiniteNumber(value) {
    if (value === undefined || value === null || value === '') {
        return null;
    }
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
}

function toBoolean(value) {
    if (typeof value === 'boolean') {
        return value;
    }
    if (typeof value === 'string') {
        const normalized = value.toLowerCase();
        if (normalized === 'true') return true;
        if (normalized === 'false') return false;
    }
    return null;
}

function toNodeMap(workflowInput) {
    if (!workflowInput) {
        return null;
    }

    let workflow = workflowInput;
    if (typeof workflowInput === 'string') {
        try {
            workflow = JSON.parse(workflowInput);
        } catch {
            return null;
        }
    }

    if (!workflow || typeof workflow !== 'object') {
        return null;
    }

    let nodes = workflow.nodes || workflow;
    if (Array.isArray(nodes)) {
        const map = {};
        nodes.forEach((node, index) => {
            const nodeId = node?.id !== undefined ? String(node.id) : String(index);
            map[nodeId] = node;
        });
        return map;
    }

    if (nodes && typeof nodes === 'object') {
        return nodes;
    }

    return null;
}

function getClassType(node) {
    return node?.class_type || node?.type || '';
}

function linkedNodeId(value) {
    if (Array.isArray(value) && value.length > 0) {
        return String(value[0]);
    }
    if (value && typeof value === 'object') {
        if (value.node_id !== undefined) {
            return String(value.node_id);
        }
        if (value.id !== undefined) {
            return String(value.id);
        }
    }
    return null;
}

function findFirstNode(nodes, classTypes) {
    if (!nodes) return null;
    const classSet = new Set(classTypes);

    for (const [nodeId, node] of Object.entries(nodes)) {
        if (classSet.has(getClassType(node))) {
            return [nodeId, node];
        }
    }

    return null;
}

function findAllNodes(nodes, classTypes) {
    if (!nodes) return [];
    const classSet = new Set(classTypes);

    return Object.entries(nodes).filter(([, node]) => classSet.has(getClassType(node)));
}

function resolveControlNetImage(nodes, startNodeId) {
    let currentNodeId = startNodeId;
    let preprocessor = 'None';
    const visited = new Set();

    while (currentNodeId && !visited.has(currentNodeId)) {
        visited.add(currentNodeId);
        const node = nodes[currentNodeId];
        if (!node) {
            return { image: null, preprocessor };
        }

        const classType = getClassType(node);
        const inputs = node.inputs || {};

        if (classType === 'LoadImage' && typeof inputs.image === 'string') {
            return { image: inputs.image, preprocessor };
        }

        if (/canny/i.test(classType)) {
            preprocessor = 'Canny';
        }

        currentNodeId = linkedNodeId(inputs.image);
    }

    return { image: null, preprocessor };
}

function normalizeCheckpoint(checkpoint) {
    if (!checkpoint) {
        return null;
    }

    if (typeof checkpoint === 'object') {
        return checkpoint;
    }

    if (typeof checkpoint === 'string') {
        return {
            name: checkpoint,
            display_name: checkpoint,
        };
    }

    return null;
}

/**
 * The model FAMILY a UNET belongs to.
 *
 * The catalogue's `base_model` is what says "this model is a UNET" - the
 * request builder and the store both read it, and a UNET lives in
 * models/unet/, not models/checkpoints/.
 *
 * The guided metadata carries the model RECORD, so its `base_model` is
 * still there. The backend's own graph-derived metadata carries only the
 * NAME, so the family has to be recovered from the model type the job
 * recorded, or from the file name.
 */
function unetBaseModel(metadata, unetName) {
    const modelType = firstDefined(metadata, ['modelType', 'model_type']);
    if (typeof modelType === 'string' && modelType === 'flux') {
        return 'flux';
    }

    const name = String(unetName || '').toLowerCase();
    if (name.includes('flux')) return 'flux';
    if (name.includes('aura')) return 'aura';
    return null;
}

function normalizeName(value) {
    if (typeof value !== 'string') {
        return '';
    }
    return value.trim().toLowerCase();
}

function candidateNames(model) {
    const names = [
        model?.name,
        model?.display_name,
        model?.filename,
        model?.file?.filename,
    ].filter((value) => typeof value === 'string' && value.trim() !== '');

    return Array.from(new Set(names));
}

function pickBestModelMatch(models, targetName) {
    if (!Array.isArray(models) || models.length === 0) {
        return null;
    }

    const normalizedTarget = normalizeName(targetName);
    if (!normalizedTarget) {
        return null;
    }

    const exact = models.find((model) => (
        candidateNames(model).some((name) => normalizeName(name) === normalizedTarget)
    ));
    if (exact) {
        return exact;
    }

    const suffixMatch = models.find((model) => (
        candidateNames(model).some((name) => normalizeName(name).endsWith(`/${normalizedTarget}`) || normalizeName(name).includes(normalizedTarget))
    ));

    return suffixMatch || null;
}

async function defaultLookupModel(directory, modelName) {
    if (!modelName) {
        return null;
    }

    const response = await filesApi.list({
        directory,
        search: modelName,
        limit: 50,
        offset: 0,
        sort: 'name_asc',
    });

    const files = response?.files || [];
    return pickBestModelMatch(files, modelName);
}

function missingModelVisuals(model) {
    if (!model || typeof model !== 'object') {
        return false;
    }

    const hasPreview = typeof model.preview === 'string' && model.preview.trim() !== '';
    const hasCivitaiId = model.civitai_id !== undefined && model.civitai_id !== null;
    return !hasPreview && !hasCivitaiId;
}

function mergeModelVisuals(targetModel, sourceModel) {
    if (!sourceModel || typeof sourceModel !== 'object') {
        return targetModel;
    }

    return {
        ...sourceModel,
        ...targetModel,
        preview: targetModel.preview || sourceModel.preview,
        civitai_id: targetModel.civitai_id ?? sourceModel.civitai_id,
        display_name: targetModel.display_name || sourceModel.display_name,
    };
}

export async function hydrateGeneratorStateModelVisuals(
    stateUpdates,
    lookupModel = defaultLookupModel,
) {
    if (!stateUpdates || typeof stateUpdates !== 'object') {
        return stateUpdates;
    }

    const hydrated = { ...stateUpdates };

    const checkpoint = hydrated.selectedCheckpoint;
    if (checkpoint && missingModelVisuals(checkpoint)) {
        const checkpointName = checkpoint.name || checkpoint.display_name;

        if (checkpointName) {
            const [checkpointMatch, unetMatch] = await Promise.all([
                lookupModel('models/checkpoints', checkpointName).catch(() => null),
                lookupModel('models/unet', checkpointName).catch(() => null),
            ]);

            const matchedCheckpoint = checkpointMatch || unetMatch;
            if (matchedCheckpoint) {
                hydrated.selectedCheckpoint = mergeModelVisuals(checkpoint, matchedCheckpoint);
            }
        }
    }

    if (Array.isArray(hydrated.selectedLoras) && hydrated.selectedLoras.length > 0) {
        const loraNames = Array.from(new Set(
            hydrated.selectedLoras
                .filter((lora) => lora && missingModelVisuals(lora))
                .map((lora) => lora.name || lora.display_name)
                .filter(Boolean)
        ));

        if (loraNames.length > 0) {
            const loraLookups = await Promise.all(
                loraNames.map(async (loraName) => {
                    const match = await lookupModel('models/loras', loraName).catch(() => null);
                    return [loraName, match];
                })
            );

            const loraByName = new Map(
                loraLookups
                    .filter(([, model]) => Boolean(model))
                    .map(([name, model]) => [normalizeName(name), model])
            );

            hydrated.selectedLoras = hydrated.selectedLoras.map((lora) => {
                if (!lora || !missingModelVisuals(lora)) {
                    return lora;
                }

                const key = normalizeName(lora.name || lora.display_name);
                const matchedLora = loraByName.get(key);
                if (!matchedLora) {
                    return lora;
                }

                return mergeModelVisuals(lora, matchedLora);
            });
        }
    }

    return hydrated;
}

function normalizeLoras(loras) {
    if (!Array.isArray(loras)) {
        return [];
    }

    return loras
        .map((lora) => {
            if (typeof lora === 'string') {
                return { name: lora, strength: 1.0 };
            }
            if (!lora || typeof lora !== 'object') {
                return null;
            }

            const name = lora.name || lora.lora_name || lora.filename;
            if (!name) {
                return null;
            }

            const rawStrength = firstDefined(lora, ['strength', 'weight', 'strength_model', 'strength_clip']);
            const strength = toFiniteNumber(rawStrength);

            return {
                ...lora,
                name,
                strength: strength ?? 1.0,
            };
        })
        .filter(Boolean);
}

function normalizeControlnets(controlnets) {
    if (!Array.isArray(controlnets)) {
        return [];
    }

    return controlnets
        .map((controlnet) => {
            if (!controlnet || typeof controlnet !== 'object') {
                return null;
            }

            const name = controlnet.name || controlnet.control_net_name || controlnet.model || '';
            const image = controlnet.image || controlnet.input || '';
            const strength = toFiniteNumber(firstDefined(controlnet, ['strength', 'weight']));
            const preprocessor = controlnet.preprocessor || 'None';

            if (!name && !image) {
                return null;
            }

            return {
                ...controlnet,
                name,
                image,
                strength: strength ?? 1.0,
                preprocessor,
            };
        })
        .filter(Boolean);
}

function extractWorkflowHints(workflowInput) {
    const nodes = toNodeMap(workflowInput);
    if (!nodes) {
        return {
            prompt: undefined,
            negativePrompt: undefined,
            seed: null,
            steps: null,
            cfg: null,
            sampler: undefined,
            scheduler: undefined,
            width: null,
            height: null,
            batchSize: null,
            checkpoint: undefined,
            vae: undefined,
            clip: undefined,
            clip2: undefined,
            loras: [],
            controlnets: [],
            adetailer: null,
            adetailerModel: undefined,
        };
    }

    let prompt;
    let negativePrompt;
    let seed = null;
    let steps = null;
    let cfg = null;
    let sampler;
    let scheduler;
    let width = null;
    let height = null;
    let batchSize = null;
    let checkpoint;
    let vae;
    let clip;
    let clip2;
    let clipSkip;
    let adetailer = null;
    let adetailerModel;

    const samplerNodeEntry = findFirstNode(nodes, ['KSampler']);
    if (samplerNodeEntry) {
        const [, samplerNode] = samplerNodeEntry;
        const samplerInputs = samplerNode.inputs || {};

        seed = toFiniteNumber(samplerInputs.seed);
        steps = toFiniteNumber(samplerInputs.steps);
        cfg = toFiniteNumber(samplerInputs.cfg);
        sampler = samplerInputs.sampler_name;
        scheduler = samplerInputs.scheduler;
        clipSkip = toFiniteNumber(samplerInputs.clip_skip);

        const positiveNodeId = linkedNodeId(samplerInputs.positive);
        const negativeNodeId = linkedNodeId(samplerInputs.negative);
        if (positiveNodeId && nodes[positiveNodeId]) {
            prompt = nodes[positiveNodeId]?.inputs?.text;
        }
        if (negativeNodeId && nodes[negativeNodeId]) {
            negativePrompt = nodes[negativeNodeId]?.inputs?.text;
        }

        const latentNodeId = linkedNodeId(samplerInputs.latent_image);
        if (latentNodeId && nodes[latentNodeId]) {
            const latentInputs = nodes[latentNodeId].inputs || {};
            width = toFiniteNumber(latentInputs.width);
            height = toFiniteNumber(latentInputs.height);
            batchSize = toFiniteNumber(latentInputs.batch_size);
        }
    }

    const checkpointEntry = findFirstNode(nodes, ['CheckpointLoaderSimple', 'CheckpointLoader']);
    if (checkpointEntry) {
        checkpoint = checkpointEntry[1]?.inputs?.ckpt_name;
    }

    if (!checkpoint) {
        const unetEntry = findFirstNode(nodes, ['UNETLoader']);
        checkpoint = unetEntry?.[1]?.inputs?.unet_name;
    }

    const vaeEntry = findFirstNode(nodes, ['VAELoader']);
    vae = vaeEntry?.[1]?.inputs?.vae_name;

    const dualClipEntry = findFirstNode(nodes, ['DualCLIPLoader']);
    if (dualClipEntry) {
        const dualInputs = dualClipEntry[1]?.inputs || {};
        clip = dualInputs.clip_name1;
        clip2 = dualInputs.clip_name2;
    } else {
        const clipEntry = findFirstNode(nodes, ['CLIPLoader']);
        clip = clipEntry?.[1]?.inputs?.clip_name;
    }

    const loras = findAllNodes(nodes, ['LoraLoader']).map(([, node]) => {
        const inputs = node.inputs || {};
        return {
            name: inputs.lora_name,
            strength: toFiniteNumber(firstDefined(inputs, ['strength_model', 'strength'])) ?? 1.0,
        };
    }).filter((lora) => Boolean(lora.name));

    const controlnets = [];
    findAllNodes(nodes, ['ControlNetApply', 'ControlNetApplyAdvanced']).forEach(([, node]) => {
        const inputs = node.inputs || {};
        const loaderNodeId = linkedNodeId(inputs.control_net);
        const imageNodeId = linkedNodeId(inputs.image);

        const controlNetName = loaderNodeId && nodes[loaderNodeId]
            ? nodes[loaderNodeId]?.inputs?.control_net_name
            : undefined;
        const { image, preprocessor } = imageNodeId
            ? resolveControlNetImage(nodes, imageNodeId)
            : { image: null, preprocessor: 'None' };

        if (controlNetName || image) {
            controlnets.push({
                name: controlNetName || '',
                image: image || '',
                strength: toFiniteNumber(inputs.strength) ?? 1.0,
                preprocessor,
            });
        }
    });

    const faceDetailerEntry = findFirstNode(nodes, ['FaceDetailer']);
    if (faceDetailerEntry) {
        adetailer = true;
    }

    const bboxEntry = findFirstNode(nodes, ['UltralyticsDetectorProvider']);
    const detectorModel = bboxEntry?.[1]?.inputs?.model_name;
    if (typeof detectorModel === 'string') {
        adetailerModel = detectorModel.split('/').pop();
    }

    return {
        prompt,
        negativePrompt,
        seed,
        steps,
        cfg,
        sampler,
        scheduler,
        clipSkip,
        width,
        height,
        batchSize,
        checkpoint,
        vae,
        clip,
        clip2,
        loras,
        controlnets,
        adetailer,
        adetailerModel,
    };
}

export function buildGeneratorStateFromMetadata(metadataInput) {
    const metadata = metadataInput && typeof metadataInput === 'object' ? metadataInput : {};
    const workflowHints = extractWorkflowHints(metadata.workflow);

    const updates = {};

    const prompt = firstDefined(metadata, ['prompt', 'positivePrompt', 'positive_prompt']) ?? workflowHints.prompt;
    if (typeof prompt === 'string') {
        updates.prompt = prompt;
    }

    const negativePrompt = firstDefined(metadata, ['negativePrompt', 'negative_prompt']) ?? workflowHints.negativePrompt;
    if (typeof negativePrompt === 'string') {
        updates.negativePrompt = negativePrompt;
    }

    const seed = toFiniteNumber(firstDefined(metadata, ['seed']) ?? workflowHints.seed);
    if (seed !== null) {
        updates.seed = Math.floor(seed);
    }

    const steps = toFiniteNumber(firstDefined(metadata, ['steps', 'num_steps']) ?? workflowHints.steps);
    if (steps !== null) {
        updates.steps = Math.floor(steps);
    }

    const cfg = toFiniteNumber(firstDefined(metadata, ['cfg', 'cfg_scale', 'cfgScale']) ?? workflowHints.cfg);
    if (cfg !== null) {
        updates.cfg = cfg;
    }

    const sampler = firstDefined(metadata, ['sampler', 'sampler_name']) ?? workflowHints.sampler;
    if (typeof sampler === 'string' && sampler) {
        updates.sampler = sampler;
    }

    const scheduler = firstDefined(metadata, ['scheduler']) ?? workflowHints.scheduler;
    if (typeof scheduler === 'string' && scheduler) {
        updates.scheduler = scheduler;
    }

    const clipSkip = toFiniteNumber(firstDefined(metadata, ['clipSkip', 'clip_skip']) ?? workflowHints.clipSkip);
    if (clipSkip !== null) {
        updates.clipSkip = Math.floor(clipSkip);
    }

    const width = toFiniteNumber(
        firstDefined(metadata, ['width', 'image_width'])
        ?? metadata?.dimensions?.width
        ?? workflowHints.width
    );
    const height = toFiniteNumber(
        firstDefined(metadata, ['height', 'image_height'])
        ?? metadata?.dimensions?.height
        ?? workflowHints.height
    );
    if (width !== null && width > 0) {
        updates.width = Math.floor(width);
    }
    if (height !== null && height > 0) {
        updates.height = Math.floor(height);
    }

    const batchSize = toFiniteNumber(firstDefined(metadata, ['batchSize', 'batch_size']) ?? workflowHints.batchSize);
    if (batchSize !== null && batchSize > 0) {
        updates.batchSize = Math.floor(batchSize);
    }

    const checkpointRaw = firstDefined(metadata, ['checkpoint', 'ckpt_name']) ?? workflowHints.checkpoint;
    const unetName = firstDefined(metadata, ['unet', 'unet_name']);
    let checkpoint = normalizeCheckpoint(checkpointRaw);
    if (unetName) {
        // A UNET model.
        //
        // The backend loads a UNET with `unet` + `clip` (+ `clip2` for
        // Flux), and the record has to SAY it is a UNET - because the
        // builder decides the loader from the record, and a UNET does not
        // live in models/checkpoints/. Without this the reuse restored a
        // model the builder read as a checkpoint, and the request asked
        // models/checkpoints/ for a file that is in models/unet/.
        const baseModel = unetBaseModel(metadata, unetName);
        const record = checkpoint || normalizeCheckpoint(unetName);
        checkpoint = {
            ...record,
            name: record.name || unetName,
            ...(baseModel && !record.base_model ? { base_model: baseModel } : {}),
        };
    }
    if (checkpoint) {
        updates.selectedCheckpoint = checkpoint;
    }

    const vae = firstDefined(metadata, ['vae', 'vae_name']) ?? workflowHints.vae;
    if (typeof vae === 'string' && vae) {
        updates.selectedVae = vae;
    }

    // The text encoders. A UNET model needs BOTH of them (Flux needs two),
    // and the guided metadata used to carry neither - so the reuse of a
    // Flux image produced a model with no text encoder at all.
    const clip = firstDefined(metadata, ['clip', 'clip_name']) ?? workflowHints.clip;
    if (typeof clip === 'string' && clip) {
        updates.selectedClip = clip;
    }

    const clip2 = firstDefined(metadata, ['clip2', 'clip_name2']) ?? workflowHints.clip2;
    if (typeof clip2 === 'string' && clip2) {
        updates.selectedClip2 = clip2;
    }

    const explicitLoras = hasOwn(metadata, 'loras');
    if (explicitLoras || workflowHints.loras.length > 0) {
        const rawLoras = explicitLoras ? metadata.loras : workflowHints.loras;
        updates.selectedLoras = normalizeLoras(rawLoras);
    }

    const explicitControlnets = hasOwn(metadata, 'controlnets');
    if (explicitControlnets || workflowHints.controlnets.length > 0) {
        const rawControlnets = explicitControlnets ? metadata.controlnets : workflowHints.controlnets;
        updates.controlnets = normalizeControlnets(rawControlnets);
    }

    const hiresFix = toBoolean(firstDefined(metadata, ['hiresFix', 'hires_fix']));
    if (hiresFix !== null) {
        updates.hiresFix = hiresFix;
    }

    const hiresUpscaler = firstDefined(metadata, ['hiresUpscaler', 'hires_upscaler']);
    if (typeof hiresUpscaler === 'string' && hiresUpscaler) {
        updates.hiresUpscaler = hiresUpscaler;
    }

    const hiresDenoise = toFiniteNumber(firstDefined(metadata, ['hiresDenoise', 'hires_denoise']));
    if (hiresDenoise !== null) {
        updates.hiresDenoise = hiresDenoise;
    }

    const hiresUpscale = toFiniteNumber(firstDefined(metadata, ['hiresUpscale', 'hires_upscale']));
    if (hiresUpscale !== null) {
        updates.hiresUpscale = hiresUpscale;
    }

    const hiresSteps = toFiniteNumber(firstDefined(metadata, ['hiresSteps', 'hires_steps']));
    if (hiresSteps !== null) {
        updates.hiresSteps = Math.floor(hiresSteps);
    }

    const adetailer = toBoolean(firstDefined(metadata, ['adetailer', 'aDetailer']) ?? workflowHints.adetailer);
    if (adetailer !== null) {
        updates.adetailer = adetailer;
    }

    const adetailerModel = firstDefined(metadata, ['adetailerModel', 'adetailer_model']) ?? workflowHints.adetailerModel;
    if (typeof adetailerModel === 'string' && adetailerModel) {
        updates.adetailerModel = adetailerModel;
    }

    const adetailerPrompt = firstDefined(metadata, ['adetailerPrompt', 'adetailer_prompt']);
    if (typeof adetailerPrompt === 'string') {
        updates.adetailerPrompt = adetailerPrompt;
    }

    const adetailerSteps = toFiniteNumber(firstDefined(metadata, ['adetailerSteps', 'adetailer_steps']));
    if (adetailerSteps !== null) {
        updates.adetailerSteps = Math.floor(adetailerSteps);
    }

    const adetailerDenoise = toFiniteNumber(firstDefined(metadata, ['adetailerDenoise', 'adetailer_denoise']));
    if (adetailerDenoise !== null) {
        updates.adetailerDenoise = adetailerDenoise;
    }

    const adetailerInpaintMasked = toBoolean(firstDefined(metadata, ['adetailerInpaintMasked', 'adetailer_inpaint_masked']));
    if (adetailerInpaintMasked !== null) {
        updates.adetailerInpaintMasked = adetailerInpaintMasked;
    }

    const cleaned = {};
    for (const [key, value] of Object.entries(updates)) {
        if (value !== undefined) {
            cleaned[key] = value;
        }
    }

    return cleaned;
}

export async function applyGeneratorStateFromMetadata(metadata) {
    const reuseState = buildGeneratorStateFromMetadata(metadata);
    if (Object.keys(reuseState).length === 0) {
        return false;
    }

    const hydratedState = await hydrateGeneratorStateModelVisuals(reuseState);
    useGeneratorStore.getState().setAll(hydratedState);
    useSettingsStore.getState().updateSetting('generator', 'autoRandomizeSeed', false);
    return true;
}
