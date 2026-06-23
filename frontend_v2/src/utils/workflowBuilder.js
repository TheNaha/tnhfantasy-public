/**
 * Utility to construct ComfyUI workflows dynamically.
 * Refactored using Strategy/Pipeline modularization for different architectures.
 */

class BasePipeline {
    constructor(builder) {
        this.builder = builder;
    }

    applyLoRAs(currentModel, currentClip, loras) {
        for (const lora of loras) {
            if (!lora.name) continue;
            const loraNode = this.builder.addNode("LoraLoader", {
                model: currentModel,
                clip: currentClip,
                lora_name: lora.name,
                strength_model: lora.strength || 1.0,
                strength_clip: lora.strength || 1.0
            });
            currentModel = [loraNode, 0];
            currentClip = [loraNode, 1];
        }
        return { currentModel, currentClip };
    }

    applyFreeU(currentModel, modelType) {
        const isSD15 = modelType === "sd15";
        const freeuNode = this.builder.addNode("FreeU_V2", {
            model: currentModel,
            b1: isSD15 ? 1.2 : 1.3,
            b2: 1.4,
            s1: 0.9,
            s2: 0.2
        });
        return [freeuNode, 0];
    }

    applyPAG(currentModel, scale) {
        const pagNode = this.builder.addNode("PerturbedAttentionGuidance", {
            model: currentModel,
            scale: scale || 3.0
        });
        return [pagNode, 0];
    }

    applyClipSkip(currentClip, skip) {
        const clipSkipNode = this.builder.addNode("CLIPSetLastLayer", {
            clip: currentClip,
            stop_at_clip_layer: -Math.abs(skip)
        });
        return [clipSkipNode, 0];
    }

    applyControlNets(positiveConditioning, controlnets) {
        let currentCond = positiveConditioning;
        for (const cn of controlnets) {
            if (!cn.name || !cn.image) continue;

            const cnLoader = this.builder.addNode("ControlNetLoader", {
                control_net_name: cn.name
            });

            const imageLoader = this.builder.addNode("LoadImage", {
                image: typeof cn.image === 'string' ? cn.image : (cn.image?.filename || cn.image)
            });

            let processedImage = [imageLoader, 0];
            if (cn.preprocessor === "Canny") {
                const canny = this.builder.addNode("CannyEdgePreprocessor", {
                    image: [imageLoader, 0],
                    low_threshold: 100,
                    high_threshold: 200,
                    resolution: 512
                });
                processedImage = [canny, 0];
            }

            const cnApply = this.builder.addNode("ControlNetApply", {
                conditioning: currentCond,
                control_net: [cnLoader, 0],
                image: processedImage,
                strength: cn.strength || 1.0
            });

            currentCond = [cnApply, 0];
        }
        return currentCond;
    }
    
    applyIPAdapters(currentModel, ipAdapters) {
        let model = currentModel;
        for (const ip of ipAdapters) {
            if (!ip.model || !ip.image || !ip.clipVision) continue;

            const ipLoader = this.builder.addNode("IPAdapterModelLoader", {
                ipadapter_file: ip.model
            });

            this.builder.addNode("CLIPVisionLoader", {
                clip_name: ip.clipVision
            });

            const imageLoader = this.builder.addNode("LoadImage", {
                image: typeof ip.image === 'string' ? ip.image : (ip.image?.filename || ip.image)
            });

            const ipApply = this.builder.addNode("IPAdapterApply", {
                ipadapter: [ipLoader, 0],
                model: model,
                weight: ip.weight || 1.0,
                image: [imageLoader, 0]
            });
            
            // Note: some custom IPAdapterApply nodes support stop_at, but we'll use standard for now
            model = [ipApply, 0];
        }
        return model;
    }

    applyLatentModifiers(latentImage, options) {
        let latent = latentImage;
        if (options.enableLatentUpscale && options.latentUpscaleMultiplier > 1.0) {
            const upscaleNode = this.builder.addNode("LatentUpscaleBy", {
                samples: latent,
                upscale_method: "bilinear",
                scale_by: options.latentUpscaleMultiplier
            });
            latent = [upscaleNode, 0];
        }
        return latent;
    }
    
    applyADetailer(finalImage, currentModel, currentClip, currentVae, options) {
        const { adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise, seed, cfg, sampler, scheduler } = options;
        const bboxLoader = this.builder.addNode("UltralyticsDetectorProvider", {
            model_name: `bbox/${adetailerModel}`
        });

        const faceDetailer = this.builder.addNode("FaceDetailer", {
            image: finalImage,
            model: currentModel,
            clip: currentClip,
            vae: currentVae,
            guide_size: 256,
            guide_size_for: true,
            max_size: 768,
            seed: seed,
            steps: adetailerSteps,
            cfg: cfg,
            sampler_name: sampler,
            scheduler: scheduler,
            denoise: adetailerDenoise,
            feather: 5,
            noise_mask: true,
            force_inpaint: true,
            bbox_threshold: 0.5,
            bbox_dilation: 10,
            bbox_crop_factor: 3.0,
            sam_detection_hint: "center-1",
            spot_percent: 0.0,
            wildcard: adetailerPrompt, 
            cycle: 1,
            bbox_detector: [bboxLoader, 0],
            sam_model_opt: null,
            segm_detector_opt: null,
            detailer_hook: null
        });

        return [faceDetailer, 0];
    }
}

class DefaultPipeline extends BasePipeline {
    loadModels(options) {
        const { checkpoint, unet, clip, clip2, vae, modelType } = options;
        let currentModel, currentClip, currentVae;

        if (unet && clip) {
            // Split Loader Mode (Flux, SD3, AuraFlow)
            currentModel = [this.builder.addNode("UNETLoader", {
                unet_name: unet,
                weight_dtype: "default"
            }), 0];
            
            if (clip2) {
                let clip1Name = clip;
                let clip2Name = clip2;
                let loaderType = "flux";

                if (modelType === "sdxl") {
                    clip1Name = clip2;
                    clip2Name = clip;
                    loaderType = "sdxl";
                }

                currentClip = [this.builder.addNode("DualCLIPLoader", {
                    clip_name1: clip1Name,
                    clip_name2: clip2Name,
                    type: loaderType
                }), 0];
            } else {
                currentClip = [this.builder.addNode("CLIPLoader", {
                    clip_name: clip,
                    type: "stable_diffusion"
                }), 0];
            }

            const vaeName = (vae && vae !== "Baked in") ? vae : "ae.safetensors";
            currentVae = [this.builder.addNode("VAELoader", {
                vae_name: vaeName
            }), 0];
            
        } else {
            // Standard Checkpoint Loader
            const checkpointLoader = this.builder.addNode("CheckpointLoaderSimple", {
                ckpt_name: checkpoint
            });
            currentModel = [checkpointLoader, 0];
            currentClip = [checkpointLoader, 1];
            currentVae = [checkpointLoader, 2];

            if (vae && vae !== "Baked in") {
                currentVae = [this.builder.addNode("VAELoader", {
                    vae_name: vae
                }), 0];
            }
        }

        return { currentModel, currentClip, currentVae };
    }

    buildCore(options, mode) {
        let { currentModel, currentClip, currentVae } = this.loadModels(options);

        // Enhancements
        if (options.clipSkip && options.clipSkip > 1) {
            currentClip = this.applyClipSkip(currentClip, options.clipSkip);
        }

        const loraRes = this.applyLoRAs(currentModel, currentClip, options.loras || []);
        currentModel = loraRes.currentModel;
        currentClip = loraRes.currentClip;

        if (options.enableFreeU && options.modelType !== "flux") {
            currentModel = this.applyFreeU(currentModel, options.modelType);
        }

        if (options.enablePAG && options.modelType !== "flux") {
            currentModel = this.applyPAG(currentModel, options.pagScale);
        }

        currentModel = this.applyIPAdapters(currentModel, options.ipAdapters || []);

        // CLIP Encoding
        let positiveConditioning = [this.builder.addNode("CLIPTextEncode", {
            text: options.prompt,
            clip: currentClip
        }), 0];

        let negativeConditioning = [this.builder.addNode("CLIPTextEncode", {
            text: options.negativePrompt,
            clip: currentClip
        }), 0];

        positiveConditioning = this.applyControlNets(positiveConditioning, options.controlnets || []);

        // Latent Setup based on mode
        let latentImage;
        if (mode === 't2i') {
            latentImage = [this.builder.addNode("EmptyLatentImage", {
                width: options.width,
                height: options.height,
                batch_size: options.batchSize || 1
            }), 0];
        } else if (mode === 'img2img') {
            const loadImage = [this.builder.addNode("LoadImage", { image: options.inputImage }), 0];
            latentImage = [this.builder.addNode("VAEEncode", {
                pixels: loadImage,
                vae: currentVae
            }), 0];
        } else if (mode === 'inpaint') {
            const loadImage = [this.builder.addNode("LoadImage", { image: options.inputImage }), 0];
            const loadMask = [this.builder.addNode("LoadImageMask", { image: options.maskImage, channel: "red" }), 0];
            
            let processedMask = loadMask;
            if (options.growMask > 0) {
                processedMask = [this.builder.addNode("GrowMask", { mask: processedMask, expand: options.growMask, tapered_corners: true }), 0];
            }
            if (options.maskBlur > 0) {
                processedMask = [this.builder.addNode("FeatherMask", { mask: processedMask, left: options.maskBlur, right: options.maskBlur, top: options.maskBlur, bottom: options.maskBlur }), 0];
            }

            latentImage = [this.builder.addNode("VAEEncodeForInpaint", {
                pixels: loadImage,
                vae: currentVae,
                mask: processedMask,
                grow_mask_by: 6
            }), 0];
        }

        latentImage = this.applyLatentModifiers(latentImage, options);

        // KSampler
        const denoise = mode === 't2i' ? 1.0 : (options.denoise || 0.7);
        let finalLatent = [this.builder.addNode("KSampler", {
            seed: options.seed,
            steps: options.steps,
            cfg: options.cfg,
            sampler_name: options.sampler,
            scheduler: options.scheduler,
            denoise: denoise,
            model: currentModel,
            positive: positiveConditioning,
            negative: negativeConditioning,
            latent_image: latentImage
        }), 0];

        // Hires Fix (T2I only)
        if (mode === 't2i' && options.hiresFix) {
            if (options.hiresUpscaler === "Latent") {
                // True Latent Upscale
                finalLatent = [this.builder.addNode("LatentUpscaleBy", {
                    samples: finalLatent,
                    upscale_method: "bilinear",
                    scale_by: options.hiresUpscale
                }), 0];
            } else {
                // Pixel-based upscale requires decoding first
                const vaeDecode1 = [this.builder.addNode("VAEDecode", { samples: finalLatent, vae: currentVae }), 0];
                let upscaleImage;
                
                if (options.hiresUpscaler === "Pixel") {
                    upscaleImage = [this.builder.addNode("ImageScaleBy", {
                        image: vaeDecode1,
                        upscale_method: "nearest-exact",
                        scale_by: options.hiresUpscale
                    }), 0];
                } else {
                    const upscalerLoader = [this.builder.addNode("UpscaleModelLoader", { model_name: options.hiresUpscaler }), 0];
                    const upscaleWithModel = [this.builder.addNode("ImageUpscaleWithModel", {
                        upscale_model: upscalerLoader,
                        image: vaeDecode1
                    }), 0];
                    const targetWidth = Math.floor(options.width * options.hiresUpscale);
                    const targetHeight = Math.floor(options.height * options.hiresUpscale);
                    upscaleImage = [this.builder.addNode("ImageScale", {
                        image: upscaleWithModel,
                        upscale_method: "lanczos",
                        width: targetWidth,
                        height: targetHeight,
                        crop: "disabled"
                    }), 0];
                }
                finalLatent = [this.builder.addNode("VAEEncode", { pixels: upscaleImage, vae: currentVae }), 0];
            }

            // Second pass KSampler for Hi-Res Fix
            finalLatent = [this.builder.addNode("KSampler", {
                seed: options.seed,
                steps: options.hiresSteps,
                cfg: options.cfg,
                sampler_name: options.sampler,
                scheduler: options.scheduler,
                denoise: options.hiresDenoise,
                model: currentModel,
                positive: positiveConditioning,
                negative: negativeConditioning,
                latent_image: finalLatent
            }), 0];
        }

        let finalImage = [this.builder.addNode("VAEDecode", { samples: finalLatent, vae: currentVae }), 0];

        if (mode === 't2i' && options.adetailer) {
            finalImage = this.applyADetailer(finalImage, currentModel, currentClip, currentVae, options);
        }

        const prefix = this.builder._generateFilenamePrefix(
            mode === 't2i' ? (options.hiresFix ? "T2I_Hires" : "T2I") :
            mode === 'img2img' ? "Img2Img" : "Inpaint"
        );

        this.builder.addNode("SaveImage", {
            filename_prefix: prefix,
            images: finalImage
        });

        return this.builder.nodes;
    }
}


export class WorkflowBuilder {
    constructor() {
        this.nodes = {};
        this.lastNodeId = 0;
    }

    addNode(classType, inputs) {
        this.lastNodeId++;
        const id = String(this.lastNodeId);
        this.nodes[id] = { inputs, class_type: classType };
        return id;
    }

    _generateFilenamePrefix(type = "T2I") {
        const now = new Date();
        const dateStr = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
        const timeStr = String(now.getHours()).padStart(2, '0') + '-' + String(now.getMinutes()).padStart(2, '0') + '-' + String(now.getSeconds()).padStart(2, '0');
        return `${type}_${dateStr}_${timeStr}`;
    }

    build(options) {
        const pipeline = new DefaultPipeline(this);
        return pipeline.buildCore(options, 't2i');
    }

    buildImg2Img(options) {
        const pipeline = new DefaultPipeline(this);
        return pipeline.buildCore(options, 'img2img');
    }

    buildInpaint(options) {
        const pipeline = new DefaultPipeline(this);
        return pipeline.buildCore(options, 'inpaint');
    }
}
