/**
 * Utility to construct ComfyUI workflows dynamically.
 */
export class WorkflowBuilder {
    constructor() {
        this.nodes = {};
        this.links = []; // Not strictly used in API format but good for mental model
        this.lastNodeId = 0;
    }

    addNode(classType, inputs) {
        this.lastNodeId++;
        const id = String(this.lastNodeId);
        this.nodes[id] = {
            inputs,
            class_type: classType
        };
        return id;
    }

    /**
     * Builds a standard T2I workflow with optional LoRAs, ControlNet, etc.
     */
    build({
        prompt,
        negativePrompt,
        seed,
        steps,
        cfg,
        sampler,
        scheduler,
        width,
        height,
        batchSize = 1,
        checkpoint,
        unet,
        clip,   // For Flux: t5xxl encoder
        clip2,  // For Flux: clip_l encoder (DualCLIPLoader)
        loras = [], // Array of { name, strength }
        controlnets = [], // Array of { name, image, strength, preprocessor }
        hiresFix = false,
        hiresUpscaler = "Latent", // "Latent" or model name
        hiresDenoise = 0.5,
        hiresUpscale = 1.5,
        hiresSteps = 10,
        adetailer = false,
        adetailerModel = "face_yolov8n.pt",
        adetailerPrompt = "",
        adetailerNegative = "",
        adetailerSteps = 20,
        adetailerDenoise = 0.4,
        adetailerInpaintMasked = true,
        vae = "Baked in",
        modelType = "flux" // "flux", "sdxl", or "sd15"
    }) {
        let currentModel, currentClip, currentVae;

        // 1. Load Model (Checkpoint or Split)
        if (unet && clip) {
            // Split Loader Mode (for Flux and other UNET-only models)
            const unetLoader = this.addNode("UNETLoader", {
                unet_name: unet,
                weight_dtype: "default"  // Required parameter: default, fp8_e4m3fn, fp8_e5m2
            });
            
            // Use DualCLIPLoader for Flux (T5XXL + CLIP-L) or SDXL (L + G)
            if (clip2) {
                let clip1Name = clip;
                let clip2Name = clip2;
                let loaderType = "flux";

                if (modelType === "sdxl") {
                    // SDXL DualCLIPLoader expects:
                    // clip_name1: CLIP-L (which is our clip2 input)
                    // clip_name2: CLIP-G (which is our clip input)
                    // type: sdxl
                    clip1Name = clip2;
                    clip2Name = clip;
                    loaderType = "sdxl";
                }

                const dualClipLoader = this.addNode("DualCLIPLoader", {
                    clip_name1: clip1Name,   // T5XXL for Flux, CLIP-L for SDXL
                    clip_name2: clip2Name,   // CLIP-L for Flux, CLIP-G for SDXL
                    type: loaderType
                });
                currentClip = [dualClipLoader, 0];
            } else {
                // Single CLIP loader fallback (Pony V7, AuraFlow, SDXL split)
                const clipLoader = this.addNode("CLIPLoader", {
                    clip_name: clip,
                    type: "stable_diffusion" // Valid types: stable_diffusion, sd3, stable_cascade, etc.
                });
                currentClip = [clipLoader, 0];
            }

            currentModel = [unetLoader, 0];

            // VAE is REQUIRED for UNET-only models (they have no baked VAE)
            // If not specified, use a default Flux VAE
            const vaeName = (vae && vae !== "Baked in") ? vae : "ae.safetensors";
            const vaeLoader = this.addNode("VAELoader", {
                vae_name: vaeName
            });
            currentVae = [vaeLoader, 0];

        } else {
            // Standard Checkpoint Mode
            const checkpointLoader = this.addNode("CheckpointLoaderSimple", {
                ckpt_name: checkpoint
            });

            currentModel = [checkpointLoader, 0];
            currentClip = [checkpointLoader, 1];
            
            // Default VAE from checkpoint
            currentVae = [checkpointLoader, 2];

            if (vae && vae !== "Baked in") {
                const vaeLoader = this.addNode("VAELoader", {
                    vae_name: vae
                });
                currentVae = [vaeLoader, 0];
            }
        }

        for (const lora of loras) {
            if (!lora.name) continue;
            const loraNode = this.addNode("LoraLoader", {
                model: currentModel,
                clip: currentClip,
                lora_name: lora.name,
                strength_model: lora.strength || 1.0,
                strength_clip: lora.strength || 1.0
            });
            currentModel = [loraNode, 0];
            currentClip = [loraNode, 1];
        }

        // 3. CLIP Text Encode (Positive)
        let positiveConditioning = this.addNode("CLIPTextEncode", {
            text: prompt,
            clip: currentClip
        });

        // 4. CLIP Text Encode (Negative)
        let negativeConditioning = this.addNode("CLIPTextEncode", {
            text: negativePrompt,
            clip: currentClip
        });

        // 5. ControlNet Chain
        for (const cn of controlnets) {
            if (!cn.name || !cn.image) continue;

            const cnLoader = this.addNode("ControlNetLoader", {
                control_net_name: cn.name
            });

            const imageLoader = this.addNode("LoadImage", {
                image: cn.image
            });

            let processedImage = [imageLoader, 0];
            if (cn.preprocessor === "Canny") {
                const canny = this.addNode("CannyEdgePreprocessor", {
                    image: [imageLoader, 0],
                    low_threshold: 100,
                    high_threshold: 200,
                    resolution: 512
                });
                processedImage = [canny, 0];
            }

            const cnApply = this.addNode("ControlNetApply", {
                conditioning: [positiveConditioning, 0],
                control_net: [cnLoader, 0],
                image: processedImage,
                strength: cn.strength || 1.0
            });

            positiveConditioning = cnApply;
        }

        // 6. Empty Latent
        const emptyLatent = this.addNode("EmptyLatentImage", {
            width: width,
            height: height,
            batch_size: batchSize
        });

        // 7. KSampler (First Pass)
        const ksampler = this.addNode("KSampler", {
            seed: seed,
            steps: steps,
            cfg: cfg,
            sampler_name: sampler,
            scheduler: scheduler,
            denoise: 1.0,
            model: currentModel,
            positive: [positiveConditioning, 0],
            negative: [negativeConditioning, 0],
            latent_image: [emptyLatent, 0]
        });

        let finalLatent = [ksampler, 0];

        // 8. Hi-Res Fix
        if (hiresFix) {
            const vaeDecode = this.addNode("VAEDecode", {
                samples: finalLatent,
                vae: currentVae
            });

            let upscaleImage;

            if (hiresUpscaler === "Latent") {
                // Latent Upscale (Old Method) - Actually this logic was pixel upscale then re-encode
                // Let's stick to Pixel Upscale -> Re-encode for "Latent" mode too as it's more stable
                // Or actually, "Latent" usually means "LatentUpscale" node.
                // But ComfyUI standard workflow is Decode -> Scale -> Encode -> KSampler.

                // Let's use standard Scale for "Latent" (Nearest Exact)
                upscaleImage = this.addNode("ImageScaleBy", {
                    image: [vaeDecode, 0],
                    upscale_method: "nearest-exact",
                    scale_by: hiresUpscale
                });
            } else {
                // Model-based Upscale
                const upscalerLoader = this.addNode("UpscaleModelLoader", {
                    model_name: hiresUpscaler
                });

                const upscaleWithModel = this.addNode("ImageUpscaleWithModel", {
                    upscale_model: [upscalerLoader, 0],
                    image: [vaeDecode, 0]
                });

                // If model upscale is fixed (e.g. 4x), we might need to downscale to target size
                // But for simplicity, let's just use the model output.
                // Wait, if user wants 1.5x but model is 4x, we should scale down.
                // Let's assume we just want the model's result for now, OR scale to target.
                // To support "scale_by", we should Scale to (width * scale_by).

                // Let's just use the model output directly if it's a model upscale, 
                // but usually HiRes fix targets a specific resolution.
                // Let's chain a Scale Image to ensure we hit the target `hiresUpscale` factor relative to original.

                // 1. Upscale with Model (e.g. 4x)
                // 2. Scale to target size (e.g. 1.5x original)

                const targetWidth = Math.floor(width * hiresUpscale);
                const targetHeight = Math.floor(height * hiresUpscale);

                upscaleImage = this.addNode("ImageScale", {
                    image: [upscaleWithModel, 0],
                    upscale_method: "lanczos",
                    width: targetWidth,
                    height: targetHeight,
                    crop: "disabled"
                });
            }

            const vaeEncode = this.addNode("VAEEncode", {
                pixels: [upscaleImage, 0],
                vae: currentVae
            });

            const ksampler2 = this.addNode("KSampler", {
                seed: seed,
                steps: hiresSteps,
                cfg: cfg,
                sampler_name: sampler,
                scheduler: scheduler,
                denoise: hiresDenoise,
                model: currentModel,
                positive: [positiveConditioning, 0],
                negative: [negativeConditioning, 0],
                latent_image: [vaeEncode, 0]
            });

            finalLatent = [ksampler2, 0];
        }

        // 9. VAE Decode (Final)
        let finalImage = this.addNode("VAEDecode", {
            samples: finalLatent,
            vae: currentVae
        });

        // 10. ADetailer
        if (adetailer) {
            // Load BBox Model
            const bboxLoader = this.addNode("UltralyticsDetectorProvider", {
                model_name: `bbox/${adetailerModel}`
            });

            // FaceDetailer
            const faceDetailer = this.addNode("FaceDetailer", {
                image: [finalImage, 0],
                model: currentModel,
                clip: currentClip,
                vae: [checkpointLoader, 2],
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
                wildcard: adetailerPrompt, // Use wildcard input for positive prompt
                cycle: 1,
                bbox_detector: [bboxLoader, 0],
                sam_model_opt: null,
                segm_detector_opt: null,
                detailer_hook: null
            });

            // Note: FaceDetailer doesn't have a direct "negative prompt" input in standard Impact Pack.
            // It uses the main CLIP negative, or we can use "Detailer (SEGS)" for more control.
            // For now, we stick to FaceDetailer. The `wildcard` input adds to positive.

            finalImage = [faceDetailer, 0];
        }

        // 11. Save Image
        const now = new Date();
        const dateStr = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
        const timeStr = String(now.getHours()).padStart(2, '0') + '-' + String(now.getMinutes()).padStart(2, '0') + '-' + String(now.getSeconds()).padStart(2, '0');
        const prefix = `Generated_${dateStr}_${timeStr}`;

        this.addNode("SaveImage", {
            filename_prefix: prefix,
            images: [finalImage, 0]
        });

        return this.nodes;
    }

    /**
     * Builds an Img2Img workflow using a source image.
     * Key difference from T2I: Uses VAEEncode on source image instead of EmptyLatent,
     * and KSampler denoise < 1.0 to preserve original features.
     */
    buildImg2Img({
        inputImage,      // Filename in ComfyUI's input folder
        prompt,
        negativePrompt,
        seed,
        steps,
        cfg,
        sampler,
        scheduler,
        denoise = 0.7,   // Key Img2Img parameter: 0.0 = keep original, 1.0 = full regeneration
        checkpoint,
        loras = [],
        vae = "Baked in"
    }) {
        // 1. Load Checkpoint
        const checkpointLoader = this.addNode("CheckpointLoaderSimple", {
            ckpt_name: checkpoint
        });

        // 1b. Load VAE (Optional)
        let currentVae = [checkpointLoader, 2];
        if (vae && vae !== "Baked in") {
            const vaeLoader = this.addNode("VAELoader", {
                vae_name: vae
            });
            currentVae = [vaeLoader, 0];
        }

        // 2. LoRA Chain
        let currentModel = [checkpointLoader, 0];
        let currentClip = [checkpointLoader, 1];

        for (const lora of loras) {
            if (!lora.name) continue;
            const loraNode = this.addNode("LoraLoader", {
                model: currentModel,
                clip: currentClip,
                lora_name: lora.name,
                strength_model: lora.strength || 1.0,
                strength_clip: lora.strength || 1.0
            });
            currentModel = [loraNode, 0];
            currentClip = [loraNode, 1];
        }

        // 3. Load Source Image
        const loadImage = this.addNode("LoadImage", {
            image: inputImage
        });

        // 4. VAE Encode (Image -> Latent)
        const vaeEncode = this.addNode("VAEEncode", {
            pixels: [loadImage, 0],
            vae: currentVae
        });

        // 5. CLIP Text Encode
        const positiveConditioning = this.addNode("CLIPTextEncode", {
            text: prompt,
            clip: currentClip
        });

        const negativeConditioning = this.addNode("CLIPTextEncode", {
            text: negativePrompt,
            clip: currentClip
        });

        // 6. KSampler with denoise < 1.0 (KEY difference from T2I)
        const ksampler = this.addNode("KSampler", {
            seed: seed,
            steps: steps,
            cfg: cfg,
            sampler_name: sampler,
            scheduler: scheduler,
            denoise: denoise,  // Img2Img denoise (0.0-1.0)
            model: currentModel,
            positive: [positiveConditioning, 0],
            negative: [negativeConditioning, 0],
            latent_image: [vaeEncode, 0]  // Source image latent
        });

        // 7. VAE Decode
        const vaeDecode = this.addNode("VAEDecode", {
            samples: [ksampler, 0],
            vae: currentVae
        });

        // 8. Save Image
        const now = new Date();
        const dateStr = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
        const timeStr = String(now.getHours()).padStart(2, '0') + '-' + String(now.getMinutes()).padStart(2, '0') + '-' + String(now.getSeconds()).padStart(2, '0');
        const prefix = `Img2Img_${dateStr}_${timeStr}`;

        this.addNode("SaveImage", {
            filename_prefix: prefix,
            images: [vaeDecode, 0]
        });

        return this.nodes;
    }

    /**
     * Builds an Inpainting workflow to regenerate masked areas.
     * Uses VAEEncodeForInpaint with mask to preserve non-masked regions.
     */
    buildInpaint({
        inputImage,      // Filename of source image in input folder
        maskImage,       // Filename of mask image in input folder
        prompt,
        negativePrompt,
        seed,
        steps,
        cfg,
        sampler,
        scheduler,
        denoise = 0.8,   // Usually higher for inpainting
        checkpoint,
        loras = [],
        vae = "Baked in",
        maskBlur = 4,    // Blur mask edges for better blending
        growMask = 6     // Expand mask slightly for better blending
    }) {
        // 1. Load Checkpoint
        const checkpointLoader = this.addNode("CheckpointLoaderSimple", {
            ckpt_name: checkpoint
        });

        // 1b. Load VAE (Optional)
        let currentVae = [checkpointLoader, 2];
        if (vae && vae !== "Baked in") {
            const vaeLoader = this.addNode("VAELoader", {
                vae_name: vae
            });
            currentVae = [vaeLoader, 0];
        }

        // 2. LoRA Chain
        let currentModel = [checkpointLoader, 0];
        let currentClip = [checkpointLoader, 1];

        for (const lora of loras) {
            if (!lora.name) continue;
            const loraNode = this.addNode("LoraLoader", {
                model: currentModel,
                clip: currentClip,
                lora_name: lora.name,
                strength_model: lora.strength || 1.0,
                strength_clip: lora.strength || 1.0
            });
            currentModel = [loraNode, 0];
            currentClip = [loraNode, 1];
        }

        // 3. Load Source Image
        const loadImage = this.addNode("LoadImage", {
            image: inputImage
        });

        // 4. Load Mask (using LoadImageMask - built-in node)
        // Canvas exports: black=keep, white=regenerate
        // ComfyUI VAEEncodeForInpaint: 1.0=inpaint, 0.0=keep (matches our canvas)
        const loadMask = this.addNode("LoadImageMask", {
            image: maskImage,
            channel: "red"  // Use red channel from RGB (white=1.0, black=0.0)
        });

        // 5. Process Mask (Optional: GrowMask + FeatherMask from Impact Pack)
        let processedMask = [loadMask, 0];

        if (growMask > 0) {
            const growNode = this.addNode("GrowMask", {
                mask: processedMask,
                expand: growMask,
                tapered_corners: true
            });
            processedMask = [growNode, 0];
        }

        if (maskBlur > 0) {
            const blurNode = this.addNode("FeatherMask", {
                mask: processedMask,
                left: maskBlur,
                right: maskBlur,
                top: maskBlur,
                bottom: maskBlur
            });
            processedMask = [blurNode, 0];
        }

        // 6. VAE Encode for Inpainting (built-in node)
        const vaeEncode = this.addNode("VAEEncodeForInpaint", {
            pixels: [loadImage, 0],
            vae: currentVae,
            mask: processedMask,
            grow_mask_by: 6
        });

        // 7. CLIP Text Encode
        const positiveConditioning = this.addNode("CLIPTextEncode", {
            text: prompt,
            clip: currentClip
        });

        const negativeConditioning = this.addNode("CLIPTextEncode", {
            text: negativePrompt,
            clip: currentClip
        });

        // 8. KSampler
        const ksampler = this.addNode("KSampler", {
            seed: seed,
            steps: steps,
            cfg: cfg,
            sampler_name: sampler,
            scheduler: scheduler,
            denoise: denoise,
            model: currentModel,
            positive: [positiveConditioning, 0],
            negative: [negativeConditioning, 0],
            latent_image: [vaeEncode, 0]
        });

        // 9. VAE Decode
        const vaeDecode = this.addNode("VAEDecode", {
            samples: [ksampler, 0],
            vae: currentVae
        });

        // 10. Save Image
        const now = new Date();
        const dateStr = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
        const timeStr = String(now.getHours()).padStart(2, '0') + '-' + String(now.getMinutes()).padStart(2, '0') + '-' + String(now.getSeconds()).padStart(2, '0');
        const prefix = `Inpaint_${dateStr}_${timeStr}`;

        this.addNode("SaveImage", {
            filename_prefix: prefix,
            images: [vaeDecode, 0]
        });

        return this.nodes;
    }
}
