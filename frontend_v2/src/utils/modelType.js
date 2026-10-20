export function isFluxModel(model) {
    const base = model?.base_model?.toLowerCase() || "";
    return base.includes('flux');
}

export function isAuraFlowModel(model) {
    const base = model?.base_model?.toLowerCase() || "";
    return base.includes('aura');
}

export function isPonyModel(model) {
    const base = model?.base_model?.toLowerCase() || "";
    return base.includes('pony 7') || base.includes('pony v7');
}

export function isUnetModel(model) {
    return isFluxModel(model) || isAuraFlowModel(model);
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
