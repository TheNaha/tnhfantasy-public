/**
 * useBatchPresets.js - user-authored Batch Generate presets
 *
 * A batch preset is a full generation configuration *plus* the prompt template
 * it expands over, including a per-LoRA weight list. It is user-authored and
 * has no backend, so it is a local preference and lives in the existing
 * localStorage-persisted `settingsStore` under `generator.batchPresets`
 * (declared in DEFAULT_SETTINGS). No third persistence mechanism is invented
 * here: this hook is the CRUD/normalisation layer over that one key.
 *
 * SERVER vs LOCAL: the installed-model lists this hook compares against come
 * from `useModelDirectories` (React Query). They are never copied into
 * settingsStore — only filenames the user *authored into a preset* are.
 *
 * SHAPE
 *   {
 *     bakedType: 'character_sheet' | 'scene_variations' | 'concept_grid' | 'custom',
 *     prompts: string[],              // template, may contain {char}/{scene}/{prompt}
 *     basePrompt, charName, sceneName,// placeholder values
 *     seedMode: 'random' | 'fixed' | 'increment',
 *     negativePrompt, steps, cfg, sampler, scheduler, clipSkip, batchSize,
 *     width, height, checkpoint, vae,
 *     loras: [{ filename, strength }],
 *   }
 *
 * LoRAs are stored as `{ filename, strength }` — a filename plus a weight, not
 * the model object Simple Generate keeps in `selectedLoras`. The model object
 * carries preview images and CivitAI metadata; persisting that into a preset
 * would bloat localStorage, and none of it survives a reinstall anyway. The
 * request still speaks the backend's `LoraOption` shape (`{ name, strength }`,
 * backend_v2/core/workflow_builder.py).
 */

import { useCallback, useMemo } from 'react';
import useSettingsStore from '../store/settingsStore';

/**
 * Hard ceiling on submitted workflows. Mirrors the backend's
 * `MAX_GENERATE_BATCH` in backend_v2/api/routes/generation.py, which answers a
 * larger body with a 400 `BATCH_TOO_LARGE`. The UI stops here so the user gets
 * a readable message instead of a round-trip rejection that creates no jobs.
 */
export const MAX_BATCH_WORKFLOWS = 60;

/** Canvas sizes offered on the page. Presets store width/height, not an index. */
export const BATCH_SIZE_OPTIONS = [
    { label: '512 × 512', width: 512, height: 512 },
    { label: '512 × 768', width: 512, height: 768 },
    { label: '768 × 768', width: 768, height: 768 },
    { label: '768 × 1024', width: 768, height: 1024 },
    { label: '1024 × 1024', width: 1024, height: 1024 },
];

export const BATCH_PRESET_KINDS = ['character_sheet', 'scene_variations', 'concept_grid', 'custom'];

export const SEED_MODES = ['random', 'fixed', 'increment'];

const EMPTY_PRESETS = {};

export const DEFAULT_BATCH_PRESET = {
    bakedType: 'character_sheet',
    prompts: [],
    basePrompt: '',
    charName: '',
    sceneName: '',
    seedMode: 'random',
    negativePrompt: '',
    steps: 28,
    cfg: 7,
    sampler: 'euler',
    scheduler: 'normal',
    clipSkip: 1,
    batchSize: 1,
    width: 1024,
    height: 1024,
    checkpoint: '',
    vae: 'Baked in',
    loras: [],
};

const LIMITS = {
    steps: [1, 150],
    cfg: [0, 30],
    clipSkip: [1, 4],
    batchSize: [1, 16],
    dimension: [64, 4096],
    strength: [-2, 2],
};

export const PRESET_FILE_KIND = 'tnhcomfy.batch-preset';
export const PRESET_FILE_VERSION = 1;

function clampNumber(value, [min, max], fallback) {
    const parsed = typeof value === 'string' ? Number(value) : value;
    if (typeof parsed !== 'number' || !Number.isFinite(parsed)) return fallback;
    return Math.min(max, Math.max(min, parsed));
}

function toText(value, fallback = '') {
    return typeof value === 'string' ? value : fallback;
}

/**
 * Store → preset LoRA shape. Only the filename and the weight are kept;
 * `preview` and the CivitAI metadata blob are deliberately dropped.
 */
export function lorasFromSelectedLoras(selectedLoras = []) {
    if (!Array.isArray(selectedLoras)) return [];
    return selectedLoras
        .filter((lora) => lora && toText(lora.name || lora.filename).trim())
        .map((lora) => ({
            filename: toText(lora.name || lora.filename).trim(),
            strength: clampNumber(lora.strength, LIMITS.strength, 1),
        }));
}

/** Preset LoRA shape → the `{ name, strength }` the backend's LoraOption reads. */
export function lorasToRequestOptions(loras = []) {
    if (!Array.isArray(loras)) return [];
    return loras
        .filter((lora) => lora && toText(lora.filename).trim())
        .map((lora) => ({ name: lora.filename, strength: Number(lora.strength) || 0 }));
}

/** Preset LoRA shape → `selectedLoras` entries for the generator store. */
export function lorasToSelectedLoras(loras = []) {
    return lorasToRequestOptions(loras).map(({ name, strength }) => ({ name, strength }));
}

function normalizeLoras(raw) {
    if (!Array.isArray(raw)) return [];
    const byFilename = new Map();
    raw.forEach((entry) => {
        if (!entry || typeof entry !== 'object') return;
        const filename = toText(entry.filename ?? entry.name).trim();
        if (!filename) return;
        // Last write wins so editing a strength in the editor is not undone by an
        // earlier duplicate row for the same file.
        byFilename.set(filename, {
            filename,
            strength: clampNumber(entry.strength, LIMITS.strength, 1),
        });
    });
    return Array.from(byFilename.values());
}

function normalizePrompts(raw) {
    if (!Array.isArray(raw)) return [];
    return raw.map((entry) => toText(entry).trim()).filter(Boolean);
}

/**
 * Coerce anything (a hand-edited localStorage blob, an imported JSON file, a
 * preset saved by an older build) into the current preset shape.
 *
 * Legacy note: the pre-parity page stored `sizeKey` (an index into the size
 * list) instead of width/height. It is still honoured on read so a preset
 * saved before this change still opens on the size the user picked.
 */
export function normalizePreset(raw, name = '') {
    const input = raw && typeof raw === 'object' ? raw : {};
    const kind = BATCH_PRESET_KINDS.includes(input.bakedType) ? input.bakedType : DEFAULT_BATCH_PRESET.bakedType;
    const seedMode = SEED_MODES.includes(input.seedMode) ? input.seedMode : DEFAULT_BATCH_PRESET.seedMode;

    let width = clampNumber(input.width, LIMITS.dimension, DEFAULT_BATCH_PRESET.width);
    let height = clampNumber(input.height, LIMITS.dimension, DEFAULT_BATCH_PRESET.height);
    if (input.width === undefined && Number.isInteger(input.sizeKey)) {
        const legacySize = BATCH_SIZE_OPTIONS[input.sizeKey];
        if (legacySize) {
            width = legacySize.width;
            height = legacySize.height;
        }
    }

    return {
        name: toText(input.name) || toText(name),
        bakedType: kind,
        prompts: normalizePrompts(input.prompts),
        basePrompt: toText(input.basePrompt),
        charName: toText(input.charName),
        sceneName: toText(input.sceneName),
        seedMode,
        negativePrompt: toText(input.negativePrompt),
        steps: Math.round(clampNumber(input.steps, LIMITS.steps, DEFAULT_BATCH_PRESET.steps)),
        cfg: clampNumber(input.cfg, LIMITS.cfg, DEFAULT_BATCH_PRESET.cfg),
        sampler: toText(input.sampler) || DEFAULT_BATCH_PRESET.sampler,
        scheduler: toText(input.scheduler) || DEFAULT_BATCH_PRESET.scheduler,
        clipSkip: Math.round(clampNumber(input.clipSkip, LIMITS.clipSkip, DEFAULT_BATCH_PRESET.clipSkip)),
        batchSize: Math.round(clampNumber(input.batchSize, LIMITS.batchSize, DEFAULT_BATCH_PRESET.batchSize)),
        width,
        height,
        checkpoint: toText(typeof input.checkpoint === 'object' ? input.checkpoint?.name : input.checkpoint),
        vae: toText(input.vae) || DEFAULT_BATCH_PRESET.vae,
        loras: normalizeLoras(input.loras),
    };
}

/** Convenience for building a preset object out of a page draft. */
export function buildPreset(draft = {}) {
    return normalizePreset({ ...draft, name: toText(draft.name) });
}

/** Human-readable one-line summary used by the preset picker. */
export function summarizePreset(preset) {
    const parts = [
        `${preset.width}×${preset.height}`,
        `${preset.steps} steps`,
        `CFG ${preset.cfg}`,
        `${preset.sampler}/${preset.scheduler}`,
    ];
    if (preset.clipSkip !== 1) parts.push(`clip ${preset.clipSkip}`);
    if (preset.batchSize !== 1) parts.push(`batch ${preset.batchSize}`);
    parts.push(preset.seedMode === 'random' ? 'random seed' : `${preset.seedMode} seed`);
    parts.push(preset.checkpoint || 'auto checkpoint');
    if (preset.loras.length > 0) {
        parts.push(`${preset.loras.length} LoRA${preset.loras.length > 1 ? 's' : ''}`);
    }
    return parts.join(' • ');
}

/**
 * Which models a preset references are not installed.
 *
 * `installed` holds the file lists React Query already fetched via
 * `useModelDirectories` — the same source ModelSelector's client-side path uses.
 * Callers must not pass the lists while they are still loading, or every
 * reference looks missing.
 */
export function findMissingModels(preset, installed = {}) {
    const installedCheckpoints = new Set(
        (installed.checkpoints || []).map((model) => model?.name).filter(Boolean)
    );
    const installedLoras = new Set(
        (installed.loras || []).map((model) => model?.name).filter(Boolean)
    );
    const missingCheckpoint = preset.checkpoint && !installedCheckpoints.has(preset.checkpoint)
        ? preset.checkpoint
        : null;
    const missingLoras = (preset.loras || [])
        .map((lora) => lora.filename)
        .filter((filename) => filename && !installedLoras.has(filename));
    return {
        missingCheckpoint,
        missingLoras,
        hasMissing: Boolean(missingCheckpoint) || missingLoras.length > 0,
    };
}

export function describeMissingModels(missing) {
    const parts = [];
    if (missing.missingCheckpoint) parts.push(`checkpoint "${missing.missingCheckpoint}"`);
    if (missing.missingLoras.length > 0) {
        parts.push(`LoRA${missing.missingLoras.length > 1 ? 's' : ''} ${missing.missingLoras.map((f) => `"${f}"`).join(', ')}`);
    }
    return parts.join(' and ');
}

/**
 * Substitute the placeholder variables into a prompt template. Every variable
 * is always available (the old code branched on the preset type and could only
 * ever resolve one of them), so a custom prompt list can mix `{char}`,
 * `{scene}` and `{prompt}` freely.
 *
 * `{char}` and `{scene}` stay literal while their field is empty, so an
 * unfilled character name still previews "portrait of {char}" rather than
 * "portrait of , front view". `{prompt}` falls back to a placeholder label.
 */
export function resolvePrompts(prompts = [], { charName = '', sceneName = '', basePrompt = '' } = {}) {
    return prompts.map((prompt) => {
        let resolved = toText(prompt);
        if (charName) resolved = resolved.replace(/\{char\}/g, charName);
        if (sceneName) resolved = resolved.replace(/\{scene\}/g, sceneName);
        return resolved.replace(/\{prompt\}/g, basePrompt || 'untitled concept');
    });
}

/** Number of workflow entries a submit would send. The backend caps this at 60. */
export function batchWorkflowCount(promptCount) {
    return Math.max(0, Number(promptCount) || 0);
}

/** Images the batch will actually produce — prompts × ComfyUI batch size. */
export function batchImageCount(promptCount, batchSize = 1) {
    return Math.max(0, Number(promptCount) || 0) * Math.max(1, Number(batchSize) || 1);
}

export function exceedsBatchLimit(promptCount) {
    return batchWorkflowCount(promptCount) > MAX_BATCH_WORKFLOWS;
}

export function batchLimitMessage(promptCount) {
    const count = batchWorkflowCount(promptCount);
    return `Too many images in this batch: ${count} workflows (limit ${MAX_BATCH_WORKFLOWS}). `
        + 'Remove some prompts or lower the batch size.';
}

export function serializePreset(name, preset) {
    return JSON.stringify(
        { kind: PRESET_FILE_KIND, version: PRESET_FILE_VERSION, name, preset: normalizePreset(preset, name) },
        null,
        2
    );
}

export function parsePresetPayload(text) {
    let payload;
    try {
        payload = JSON.parse(text);
    } catch {
        throw new Error('That file is not valid JSON');
    }
    if (!payload || typeof payload !== 'object') {
        throw new Error('That file is not a batch preset');
    }
    if (payload.kind && payload.kind !== PRESET_FILE_KIND) {
        throw new Error('That file is not a TNHComfy batch preset');
    }
    const raw = payload.preset && typeof payload.preset === 'object' ? payload.preset : payload;
    const name = toText(raw.name) || toText(payload.name);
    if (!name) {
        throw new Error('That preset has no name');
    }
    return normalizePreset(raw, name);
}

/**
 * Trigger a browser download, matching the export convention already used by
 * PromptLibrary and StoryReader (Blob → object URL → anchor click → revoke).
 */
export function downloadPresetJson(name, preset) {
    const blob = new Blob([serializePreset(name, preset)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `batch-preset-${name.replace(/[^\w.-]+/g, '_')}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
}

function uniqueName(base, taken) {
    if (!taken.has(base)) return base;
    let suffix = 2;
    while (taken.has(`${base} ${suffix}`)) suffix += 1;
    return `${base} ${suffix}`;
}

/**
 * CRUD over `settingsStore.settings.generator.batchPresets`, an object keyed
 * by preset name. Writes go through `updateSetting` so the existing persist
 * middleware (localStorage, `comfyui-settings-storage`) saves them — the same
 * path the pre-parity page used, so presets already on disk keep working.
 */
export function useBatchPresets() {
    const storedPresets = useSettingsStore((state) => state.settings?.generator?.batchPresets || EMPTY_PRESETS);
    const updateSetting = useSettingsStore((state) => state.updateSetting);

    const write = useCallback((next) => {
        updateSetting('generator', 'batchPresets', next);
    }, [updateSetting]);

    const presets = useMemo(() => {
        return Object.entries(storedPresets)
            .map(([name, preset]) => normalizePreset(preset, name))
            .sort((a, b) => a.name.localeCompare(b.name));
    }, [storedPresets]);

    const presetNames = useMemo(() => presets.map((preset) => preset.name), [presets]);

    const getPreset = useCallback(
        (name) => (name && storedPresets[name] ? normalizePreset(storedPresets[name], name) : null),
        [storedPresets]
    );

    const savePreset = useCallback((name, preset) => {
        const trimmed = toText(name).trim();
        if (!trimmed) return { ok: false, error: 'Enter a preset name' };
        const normalized = normalizePreset({ ...preset, name: trimmed }, trimmed);
        write({ ...storedPresets, [trimmed]: normalized });
        return { ok: true, name: trimmed, preset: normalized, replaced: Object.hasOwn(storedPresets, trimmed) };
    }, [storedPresets, write]);

    const renamePreset = useCallback((fromName, nextName) => {
        const trimmed = toText(nextName).trim();
        if (!trimmed) return { ok: false, error: 'Enter a preset name' };
        if (trimmed === fromName) return { ok: true, name: trimmed };
        if (Object.hasOwn(storedPresets, trimmed)) {
            return { ok: false, error: `A preset named "${trimmed}" already exists` };
        }
        const source = storedPresets[fromName];
        if (!source) return { ok: false, error: 'That preset no longer exists' };
        const next = {};
        Object.entries(storedPresets).forEach(([name, preset]) => {
            if (name === fromName) {
                next[trimmed] = normalizePreset({ ...preset, name: trimmed }, trimmed);
            } else {
                next[name] = preset;
            }
        });
        write(next);
        return { ok: true, name: trimmed };
    }, [storedPresets, write]);

    const deletePreset = useCallback((name) => {
        if (!Object.hasOwn(storedPresets, name)) return { ok: false };
        const next = { ...storedPresets };
        delete next[name];
        write(next);
        return { ok: true };
    }, [storedPresets, write]);

    /** Copy an existing preset (or a baked template draft) under a new name. */
    const duplicatePreset = useCallback((sourceName, suggestedName) => {
        const source = storedPresets[sourceName];
        if (!source) return { ok: false, error: 'That preset no longer exists' };
        const name = uniqueName(toText(suggestedName).trim() || `${sourceName} copy`, new Set(Object.keys(storedPresets)));
        const copy = normalizePreset({ ...source, name }, name);
        write({ ...storedPresets, [name]: copy });
        return { ok: true, name, preset: copy };
    }, [storedPresets, write]);

    const exportPreset = useCallback((name) => {
        const preset = getPreset(name);
        if (!preset) return { ok: false, error: 'That preset no longer exists' };
        downloadPresetJson(name, preset);
        return { ok: true, name };
    }, [getPreset]);

    const importPreset = useCallback((name, preset) => savePreset(name, preset), [savePreset]);

    /** Read a `.json` file and save it, returning `{ ok, name }` or `{ ok, error }`. */
    const importPresetFile = useCallback((file) => new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = (event) => {
            try {
                const parsed = parsePresetPayload(event.target.result);
                const name = uniqueName(parsed.name, new Set(Object.keys(storedPresets)));
                const result = savePreset(name, parsed);
                resolve(result.ok ? { ok: true, name } : { ok: false, error: result.error });
            } catch (error) {
                resolve({ ok: false, error: error.message });
            }
        };
        reader.onerror = () => resolve({ ok: false, error: 'Could not read that file' });
        reader.readAsText(file);
    }), [storedPresets, savePreset]);

    return {
        presets,
        presetNames,
        getPreset,
        savePreset,
        renamePreset,
        duplicatePreset,
        deletePreset,
        exportPreset,
        importPreset,
        importPresetFile,
    };
}

export default useBatchPresets;
