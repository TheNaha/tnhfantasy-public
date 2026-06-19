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
