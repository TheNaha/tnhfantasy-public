import { describe, it, expect, beforeEach } from 'vitest';
import { WorkflowBuilder } from '../utils/workflowBuilder';

describe('WorkflowBuilder', () => {
    let builder;

    beforeEach(() => {
        builder = new WorkflowBuilder();
    });

    describe('constructor', () => {
        it('initializes with empty nodes', () => {
            expect(builder.nodes).toEqual({});
        });

        it('starts with lastNodeId of 0', () => {
            expect(builder.lastNodeId).toBe(0);
        });
    });

    describe('addNode', () => {
        it('adds a node and returns its string ID', () => {
            const id = builder.addNode('KSampler', { seed: 42 });
            expect(id).toBe('1');
            expect(builder.nodes['1']).toBeDefined();
        });

        it('increments node IDs sequentially', () => {
            const id1 = builder.addNode('NodeA', {});
            const id2 = builder.addNode('NodeB', {});
            const id3 = builder.addNode('NodeC', {});
            expect(id1).toBe('1');
            expect(id2).toBe('2');
            expect(id3).toBe('3');
        });

        it('stores class_type and inputs correctly', () => {
            builder.addNode('CheckpointLoaderSimple', { ckpt_name: 'model.safetensors' });
            expect(builder.nodes['1'].class_type).toBe('CheckpointLoaderSimple');
            expect(builder.nodes['1'].inputs.ckpt_name).toBe('model.safetensors');
        });
    });

    describe('build (T2I workflow)', () => {
        const baseParams = {
            prompt: 'a beautiful landscape',
            negativePrompt: 'blur, low quality',
            seed: 12345,
            steps: 20,
            cfg: 7.0,
            sampler: 'euler',
            scheduler: 'normal',
            width: 512,
            height: 512,
            checkpoint: 'model.safetensors',
            modelType: 'sdxl',
        };

        it('returns a non-empty nodes object', () => {
            const nodes = builder.build(baseParams);
            expect(typeof nodes).toBe('object');
            expect(Object.keys(nodes).length).toBeGreaterThan(0);
        });

        it('includes a CheckpointLoaderSimple node', () => {
            const nodes = builder.build(baseParams);
            const checkpointNode = Object.values(nodes).find(
                n => n.class_type === 'CheckpointLoaderSimple'
            );
            expect(checkpointNode).toBeDefined();
            expect(checkpointNode.inputs.ckpt_name).toBe('model.safetensors');
        });

        it('includes KSampler with correct params', () => {
            const nodes = builder.build(baseParams);
            const ksampler = Object.values(nodes).find(n => n.class_type === 'KSampler');
            expect(ksampler).toBeDefined();
            expect(ksampler.inputs.seed).toBe(12345);
            expect(ksampler.inputs.steps).toBe(20);
            expect(ksampler.inputs.cfg).toBe(7.0);
        });

        it('includes SaveImage node', () => {
            const nodes = builder.build(baseParams);
            const saveImage = Object.values(nodes).find(n => n.class_type === 'SaveImage');
            expect(saveImage).toBeDefined();
        });

        it('includes EmptyLatentImage with correct dimensions', () => {
            const nodes = builder.build(baseParams);
            const latent = Object.values(nodes).find(n => n.class_type === 'EmptyLatentImage');
            expect(latent).toBeDefined();
            expect(latent.inputs.width).toBe(512);
            expect(latent.inputs.height).toBe(512);
        });

        it('includes CLIPTextEncode nodes for positive and negative', () => {
            const nodes = builder.build(baseParams);
            const textEncoders = Object.values(nodes).filter(n => n.class_type === 'CLIPTextEncode');
            expect(textEncoders.length).toBe(2);
            const texts = textEncoders.map(n => n.inputs.text);
            expect(texts).toContain('a beautiful landscape');
            expect(texts).toContain('blur, low quality');
        });

        it('includes VAEDecode node', () => {
            const nodes = builder.build(baseParams);
            const vaeDecode = Object.values(nodes).find(n => n.class_type === 'VAEDecode');
            expect(vaeDecode).toBeDefined();
        });

        it('adds LoRA nodes when loras provided', () => {
            const nodes = builder.build({
                ...baseParams,
                loras: [{ name: 'my_lora.safetensors', strength: 0.8 }],
            });
            const loraNode = Object.values(nodes).find(n => n.class_type === 'LoraLoader');
            expect(loraNode).toBeDefined();
            expect(loraNode.inputs.lora_name).toBe('my_lora.safetensors');
            expect(loraNode.inputs.strength_model).toBe(0.8);
        });

        it('skips LoRA nodes with empty name', () => {
            const nodes = builder.build({
                ...baseParams,
                loras: [{ name: '', strength: 1.0 }],
            });
            const loraNode = Object.values(nodes).find(n => n.class_type === 'LoraLoader');
            expect(loraNode).toBeUndefined();
        });

        it('adds multiple LoRA nodes chained', () => {
            const nodes = builder.build({
                ...baseParams,
                loras: [
                    { name: 'lora1.safetensors', strength: 0.8 },
                    { name: 'lora2.safetensors', strength: 0.5 },
                ],
            });
            const loraNodes = Object.values(nodes).filter(n => n.class_type === 'LoraLoader');
            expect(loraNodes.length).toBe(2);
        });

        it('adds HiresFix nodes when hiresFix is true', () => {
            const nodes = builder.build({
                ...baseParams,
                hiresFix: true,
                hiresUpscaler: 'Latent',
                hiresDenoise: 0.5,
                hiresUpscale: 1.5,
                hiresSteps: 10,
            });
            const ksamplers = Object.values(nodes).filter(n => n.class_type === 'KSampler');
            expect(ksamplers.length).toBe(2); // First pass + HiresFix pass
        });

        it('uses external VAE loader when vae is not Baked in', () => {
            const nodes = builder.build({
                ...baseParams,
                vae: 'my_vae.pt',
            });
            const vaeLoader = Object.values(nodes).find(n => n.class_type === 'VAELoader');
            expect(vaeLoader).toBeDefined();
            expect(vaeLoader.inputs.vae_name).toBe('my_vae.pt');
        });

        it('uses UNETLoader when unet is specified', () => {
            const nodes = builder.build({
                ...baseParams,
                checkpoint: undefined,
                unet: 'flux_unet.safetensors',
                clip: 't5xxl.safetensors',
                modelType: 'flux',
            });
            const unetLoader = Object.values(nodes).find(n => n.class_type === 'UNETLoader');
            expect(unetLoader).toBeDefined();
            expect(unetLoader.inputs.unet_name).toBe('flux_unet.safetensors');
        });

        it('uses DualCLIPLoader for Flux model with two clips', () => {
            const nodes = builder.build({
                ...baseParams,
                checkpoint: undefined,
                unet: 'flux_unet.safetensors',
                clip: 't5xxl.safetensors',
                clip2: 'clip_l.safetensors',
                modelType: 'flux',
            });
            const dualClip = Object.values(nodes).find(n => n.class_type === 'DualCLIPLoader');
            expect(dualClip).toBeDefined();
            expect(dualClip.inputs.type).toBe('flux');
        });

        it('uses DualCLIPLoader with sdxl type for SDXL split model', () => {
            const nodes = builder.build({
                ...baseParams,
                checkpoint: undefined,
                unet: 'sdxl_unet.safetensors',
                clip: 'clip_g.safetensors',
                clip2: 'clip_l.safetensors',
                modelType: 'sdxl',
            });
            const dualClip = Object.values(nodes).find(n => n.class_type === 'DualCLIPLoader');
            expect(dualClip).toBeDefined();
            expect(dualClip.inputs.type).toBe('sdxl');
        });

        it('includes batch_size in EmptyLatentImage', () => {
            const nodes = builder.build({ ...baseParams, batchSize: 4 });
            const latent = Object.values(nodes).find(n => n.class_type === 'EmptyLatentImage');
            expect(latent.inputs.batch_size).toBe(4);
        });
    });

    describe('buildImg2Img', () => {
        const baseParams = {
            inputImage: 'source.png',
            prompt: 'a cat',
            negativePrompt: 'blur',
            seed: 42,
            steps: 20,
            cfg: 7.0,
            sampler: 'euler',
            scheduler: 'normal',
            denoise: 0.7,
            checkpoint: 'model.safetensors',
        };

        it('returns a non-empty nodes object', () => {
            const nodes = builder.buildImg2Img(baseParams);
            expect(Object.keys(nodes).length).toBeGreaterThan(0);
        });

        it('includes LoadImage node with correct filename', () => {
            const nodes = builder.buildImg2Img(baseParams);
            const loadImage = Object.values(nodes).find(n => n.class_type === 'LoadImage');
            expect(loadImage).toBeDefined();
            expect(loadImage.inputs.image).toBe('source.png');
        });

        it('includes VAEEncode node (not EmptyLatentImage)', () => {
            const nodes = builder.buildImg2Img(baseParams);
            const vaeEncode = Object.values(nodes).find(n => n.class_type === 'VAEEncode');
            expect(vaeEncode).toBeDefined();
            const emptyLatent = Object.values(nodes).find(n => n.class_type === 'EmptyLatentImage');
            expect(emptyLatent).toBeUndefined();
        });

        it('KSampler uses the provided denoise value', () => {
            const nodes = builder.buildImg2Img({ ...baseParams, denoise: 0.4 });
            const ksampler = Object.values(nodes).find(n => n.class_type === 'KSampler');
            expect(ksampler.inputs.denoise).toBe(0.4);
        });

        it('includes SaveImage with Img2Img prefix', () => {
            const nodes = builder.buildImg2Img(baseParams);
            const saveImage = Object.values(nodes).find(n => n.class_type === 'SaveImage');
            expect(saveImage).toBeDefined();
            expect(saveImage.inputs.filename_prefix).toMatch(/^Img2Img_/);
        });
    });

    describe('buildInpaint', () => {
        const baseParams = {
            inputImage: 'source.png',
            maskImage: 'mask.png',
            prompt: 'a dog',
            negativePrompt: 'blur',
            seed: 42,
            steps: 20,
            cfg: 7.0,
            sampler: 'euler',
            scheduler: 'normal',
            denoise: 0.8,
            checkpoint: 'model.safetensors',
        };

        it('returns a non-empty nodes object', () => {
            const nodes = builder.buildInpaint(baseParams);
            expect(Object.keys(nodes).length).toBeGreaterThan(0);
        });

        it('includes LoadImageMask node for the mask', () => {
            const nodes = builder.buildInpaint(baseParams);
            const maskLoader = Object.values(nodes).find(n => n.class_type === 'LoadImageMask');
            expect(maskLoader).toBeDefined();
            expect(maskLoader.inputs.image).toBe('mask.png');
        });

        it('includes VAEEncodeForInpaint instead of VAEEncode', () => {
            const nodes = builder.buildInpaint(baseParams);
            const inpaintEncode = Object.values(nodes).find(n => n.class_type === 'VAEEncodeForInpaint');
            expect(inpaintEncode).toBeDefined();
        });

        it('includes GrowMask when growMask > 0', () => {
            const nodes = builder.buildInpaint({ ...baseParams, growMask: 6 });
            const growMask = Object.values(nodes).find(n => n.class_type === 'GrowMask');
            expect(growMask).toBeDefined();
            expect(growMask.inputs.expand).toBe(6);
        });

        it('skips GrowMask when growMask is 0', () => {
            const nodes = builder.buildInpaint({ ...baseParams, growMask: 0 });
            const growMask = Object.values(nodes).find(n => n.class_type === 'GrowMask');
            expect(growMask).toBeUndefined();
        });

        it('includes FeatherMask when maskBlur > 0', () => {
            const nodes = builder.buildInpaint({ ...baseParams, maskBlur: 4 });
            const feather = Object.values(nodes).find(n => n.class_type === 'FeatherMask');
            expect(feather).toBeDefined();
        });

        it('includes SaveImage with Inpaint prefix', () => {
            const nodes = builder.buildInpaint(baseParams);
            const saveImage = Object.values(nodes).find(n => n.class_type === 'SaveImage');
            expect(saveImage).toBeDefined();
            expect(saveImage.inputs.filename_prefix).toMatch(/^Inpaint_/);
        });
    });
});
