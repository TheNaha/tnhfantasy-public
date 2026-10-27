import { describe, expect, it } from 'vitest';

import { buildGeneratorPayload } from '../hooks/useWorkflowBuilder';
import { buildGeneratorStateFromMetadata } from '../utils/reuseParameters';

/**
 * One request builder, and the metadata that describes what it asked for.
 *
 * Two defects are pinned here, both about the model a request names:
 *
 *  1. The guided metadata carried only `checkpoint` and `vae`. A UNET model
 *     is loaded from `unet` + `clip` (+ `clip2` for Flux), so the metadata
 *     never said which loader the job used - and "Reuse parameters" on a Flux
 *     image produced a model with no text encoder, which the backend then
 *     rejected.
 *
 *  2. `embeddings` and `shortcuts` were written into every t2i job's
 *     metadata and read by nobody: the backend expands the shortcuts and
 *     validates the embeddings itself, so the frontend's copy was pure
 *     payload on every job row.
 *
 * The builder also states the KIND of the request it produces, so the API
 * layer never has to guess which shape it is holding.
 */

const FLUX = {
    name: 'flux1-dev.safetensors',
    display_name: 'Flux 1 Dev',
    base_model: 'flux_1',
};

describe('the shared request builder', () => {
    it('states the kind of the request it builds', () => {
        const { options } = buildGeneratorPayload('t2i', { prompt: 'a cat' });

        expect(options.kind).toBe('guided');
    });

    it('names a UNET model with its text encoders', () => {
        const { options } = buildGeneratorPayload('t2i', {
            prompt: 'a cat',
            selectedCheckpoint: FLUX,
            selectedClip: 't5xxl_fp16.safetensors',
            selectedClip2: 'clip_l.safetensors',
            selectedVae: 'Baked in',
        });

        // A UNET is loaded from `unet` + `clip`, not from `checkpoint`.
        expect(options.checkpoint).toBeNull();
        expect(options.unet).toBe('flux1-dev.safetensors');
        expect(options.clip).toBe('t5xxl_fp16.safetensors');
        expect(options.clip2).toBe('clip_l.safetensors');
        expect(options.modelType).toBe('flux');
    });

    it('records the model it used in the metadata', () => {
        const { metadata } = buildGeneratorPayload('t2i', {
            prompt: 'a cat',
            selectedCheckpoint: FLUX,
            selectedClip: 't5xxl_fp16.safetensors',
            selectedClip2: 'clip_l.safetensors',
            selectedVae: 'Baked in',
        });

        // Without these the gallery and "Reuse parameters" had no way to tell
        // that the job ran a UNET rather than a checkpoint.
        expect(metadata.unet).toBe('flux1-dev.safetensors');
        expect(metadata.clip).toBe('t5xxl_fp16.safetensors');
        expect(metadata.clip2).toBe('clip_l.safetensors');
        expect(metadata.modelType).toBe('flux');
    });

    it('records a checkpoint model the same way', () => {
        const { options, metadata } = buildGeneratorPayload('t2i', {
            prompt: 'a cat',
            selectedCheckpoint: { name: 'sdxl.safetensors', base_model: 'sdxl_1_0' },
            selectedVae: 'Baked in',
        });

        expect(options.checkpoint).toBe('sdxl.safetensors');
        expect(options.unet).toBeNull();
        expect(options.clip).toBeNull();
        expect(metadata.checkpoint).toEqual({ name: 'sdxl.safetensors', base_model: 'sdxl_1_0' });
        expect(metadata.unet).toBeNull();
        expect(metadata.modelType).toBe('sdxl');
    });

    it('writes no embeddings and no shortcuts into the metadata', () => {
        const { metadata } = buildGeneratorPayload('t2i', {
            prompt: 'a cat, <lora:style:0.5>',
            selectedCheckpoint: FLUX,
        });

        // The backend expands the shortcuts and validates the embeddings
        // itself. Nothing on either side read these.
        expect(metadata).not.toHaveProperty('embeddings');
        expect(metadata).not.toHaveProperty('shortcuts');
    });

    it('keeps a LoRA that was deliberately turned off', () => {
        const { options } = buildGeneratorPayload('t2i', {
            prompt: 'a cat',
            selectedLoras: [{ name: 'style.safetensors', strength: 0 }],
        });

        expect(options.loras[0].strength).toBe(0);
    });

    it('preserves LoRA strengths beyond 2.0 and negative strengths without clamping', () => {
        const { options } = buildGeneratorPayload('t2i', {
            prompt: 'a cat',
            selectedLoras: [
                { name: 'slider_heavy.safetensors', strength: 3.0 },
                { name: 'slider_neg.safetensors', strength: -2.5 },
            ],
        });

        expect(options.loras[0].strength).toBe(3.0);
        expect(options.loras[1].strength).toBe(-2.5);
    });

    it('keeps an IP adapter\'s "Stop At"', () => {
        const { options } = buildGeneratorPayload('t2i', {
            prompt: 'a cat',
            ipAdapters: [{
                model: 'ip-adapter-plus.safetensors',
                clipVision: 'clip_vision_h.safetensors',
                image: 'ref.png',
                weight: 0.8,
                stopAt: 0.4,
            }],
        });

        expect(options.ipAdapters[0].stopAt).toBe(0.4);
    });

    it('takes a model that is already resolved, for a caller with no store', () => {
        // "Quick Remix" rebuilds a request from a finished job's metadata: it
        // has names, not the model RECORD, so the loader has to be stated.
        const { options } = buildGeneratorPayload('t2i', {
            prompt: 'a cat',
            model: {
                checkpoint: null,
                unet: 'flux1-dev.safetensors',
                clip: 't5xxl_fp16.safetensors',
                clip2: 'clip_l.safetensors',
                vae: 'ae.safetensors',
                modelType: 'flux',
            },
        });

        expect(options.unet).toBe('flux1-dev.safetensors');
        expect(options.clip).toBe('t5xxl_fp16.safetensors');
        expect(options.clip2).toBe('clip_l.safetensors');
        expect(options.checkpoint).toBeNull();
        expect(options.modelType).toBe('flux');
    });
});

describe('reusing the parameters of a job', () => {
    it('restores a UNET model from a job\'s own metadata', () => {
        // The end-to-end shape: a job is generated, and its metadata is
        // enough to reproduce it. The metadata used to carry only
        // `checkpoint` and `vae`, so the reuse produced a model with no text
        // encoder - and the backend rejected the UNET that came with it.
        const { metadata } = buildGeneratorPayload('t2i', {
            prompt: 'a cat',
            selectedCheckpoint: FLUX,
            selectedClip: 't5xxl_fp16.safetensors',
            selectedClip2: 'clip_l.safetensors',
            selectedVae: 'Baked in',
        });

        const updates = buildGeneratorStateFromMetadata(metadata);

        expect(updates.selectedCheckpoint?.name).toBe('flux1-dev.safetensors');
        expect(updates.selectedClip).toBe('t5xxl_fp16.safetensors');
        expect(updates.selectedClip2).toBe('clip_l.safetensors');
    });

    it('restores a UNET model with both of its text encoders', () => {
        const updates = buildGeneratorStateFromMetadata({
            type: 't2i',
            checkpoint: FLUX,
            unet: 'flux1-dev.safetensors',
            clip: 't5xxl_fp16.safetensors',
            clip2: 'clip_l.safetensors',
            modelType: 'flux',
        });

        expect(updates.selectedCheckpoint?.name).toBe('flux1-dev.safetensors');
        expect(updates.selectedClip).toBe('t5xxl_fp16.safetensors');
        expect(updates.selectedClip2).toBe('clip_l.safetensors');
    });

    it('restores a UNET whose metadata carried only the file name', () => {
        // The backend's own graph-derived metadata carries names, not the
        // model record - so the record has to be rebuilt, WITH the family,
        // because the family is what says "this is a UNET, and a UNET does
        // not live in models/checkpoints/".
        const updates = buildGeneratorStateFromMetadata({
            checkpoint: 'flux1-dev.safetensors',
            unet: 'flux1-dev.safetensors',
            modelType: 'flux',
        });

        expect(updates.selectedCheckpoint?.name).toBe('flux1-dev.safetensors');
        expect(updates.selectedCheckpoint?.base_model).toBe('flux');
    });

    it('leaves a checkpoint model alone', () => {
        const updates = buildGeneratorStateFromMetadata({
            checkpoint: 'sdxl.safetensors',
        });

        expect(updates.selectedCheckpoint).toEqual({
            name: 'sdxl.safetensors',
            display_name: 'sdxl.safetensors',
        });
        expect(updates.selectedClip).toBeUndefined();
        expect(updates.selectedClip2).toBeUndefined();
    });
});
