export function isFluxModel(model) {
    const base = (model?.base_model || model?.baseModel || "").toLowerCase();
    return base.includes('flux');
}

export function isAuraFlowModel(model) {
    const base = (model?.base_model || model?.baseModel || "").toLowerCase();
    return base.includes('aura');
}

export function isPonyModel(model) {
    const base = (model?.base_model || model?.baseModel || "").toLowerCase();
    return base.includes('pony');
}

export function isUnetModel(model) {
    return isFluxModel(model) || isAuraFlowModel(model);
}

export function getModelFamily(modelOrBase) {
    const raw = (typeof modelOrBase === 'string' ? modelOrBase : (modelOrBase?.base_model || modelOrBase?.baseModel || '')).toLowerCase().trim();
    if (!raw) return 'unknown';
    if (raw.includes('flux')) return 'flux';
    if (raw.includes('pony')) return 'pony';
    if (raw.includes('illustrious') || raw.includes('noob')) return 'illustrious';
    if (raw.includes('sdxl') || raw.includes('stable-diffusion-xl') || raw.includes('stable diffusion xl')) return 'sdxl';
    if (raw.includes('sd 3') || raw.includes('sd3')) return 'sd3';
    if (raw.includes('aura')) return 'auraflow';
    if (raw.includes('sd 1') || raw.includes('sd1') || raw.includes('sd 2') || raw.includes('sd2')) return 'sd15';
    if (raw.includes('hunyuan')) return 'hunyuan';
    if (raw.includes('wan')) return 'wan';
    return raw;
}

export function areModelsCompatible(checkpoint, lora) {
    if (!checkpoint || !lora) return true;
    const ckptFamily = getModelFamily(checkpoint);
    const loraFamily = getModelFamily(lora);
    if (ckptFamily === 'unknown' || loraFamily === 'unknown') return true;
    if (ckptFamily === loraFamily) return true;

    // Both belong to the SDXL architecture family (SDXL, Pony, Illustrious, NoobAI)
    const isSdxlArch = (fam) => fam === 'sdxl' || fam === 'pony' || fam === 'illustrious';
    if (isSdxlArch(ckptFamily) && isSdxlArch(loraFamily)) {
        return true;
    }

    return false;
}
/**
 * The model family, as the backend's `modelType` option.
 *
 * The backend uses it for two things: which FreeU curve to use (the SD1.5
 * curve and the SDXL curve are different) and which layout the dual CLIP
 * loader gets. Getting it wrong is not cosmetic - an SD3 checkpoint read
 * as `sd15` gets the SD1.5 FreeU curve.
 *
 * It used to be derived from three name checks and defaulted to `sd15`, so
 * SD3 and Illustrious were read as SD1.5: SD3 is an SDXL-family model with
 * its own CLIP pair, and Illustrious is an SDXL finetune. The catalogue's
 * `base_model` is the authority, and it is what the other three checks
 * already read.
 *
 * The three values are the ones the backend understands: `flux`, `sdxl`
 * and `sd15`. SD3 reads as `sdxl` because that is the layout and the
 * curve it needs.
 */
export function resolveModelType(model) {
    const base = (model?.base_model || '').toLowerCase().trim();

    if (base.includes('flux')) return 'flux';

    if (
        base.includes('sd3') ||
        base.includes('sdxl') ||
        base.includes('pony') ||
        base.includes('aura') ||
        base.includes('illustrious')
    ) {
        return 'sdxl';
    }

    return 'sd15';
}
