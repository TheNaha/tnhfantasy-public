export function getCheckpointDisplayName(source) {
    if (!source) return null;

    const checkpointValue = source.checkpoint ?? source.metadata?.checkpoint ?? source.metadata_?.checkpoint;

    if (!checkpointValue) return null;

    const rawName = typeof checkpointValue === 'object'
        ? checkpointValue.display_name || checkpointValue.name
        : checkpointValue;

    if (typeof rawName !== 'string') return null;

    return rawName.replace('.safetensors', '');
}

/**
 * A job's checkpoint FILE NAME, whichever shape the metadata carried it in.
 *
 * The guided path sends the model RECORD - an object with `name`,
 * `display_name` and the visual fields, because the gallery shows them.
 * The backend's own graph-derived metadata sends the NAME, because the
 * backend does not know the record.
 *
 * So both shapes are legitimate, and four places were reading them with
 * their own copy of the same ternary.
 */
export function checkpointName(metadata) {
    const value = metadata?.checkpoint;
    if (!value) return null;
    if (typeof value === 'object') return value.name || null;
    return typeof value === 'string' ? value : null;
}

/**
 * Hydrate a model with version-specific metadata (file, preview image, base_model, trained_words).
 */
export function getModelWithVersion(model, version) {
    if (!version) return model;
    const file = version.file || {};
    const versionImages = version.images || [];
    const selectedVersionPreviewId = version.civitai_version_id || version.id;
    const directPreviewImage = versionImages[0]?.url || model.preview;
    const proxyPreviewImage = model.civitai_id
        ? (() => {
            const params = new URLSearchParams({ image_index: '0' });
            if (selectedVersionPreviewId) {
                params.set('version_id', String(selectedVersionPreviewId));
            }
            return `/api/v2/models/preview/${model.civitai_id}?${params.toString()}`;
        })()
        : null;
    const previewImage = directPreviewImage || proxyPreviewImage;

    return {
        ...model,
        name: file.filename || model.name,
        display_name: model.display_name,
        civitai_id: model.civitai_id,
        preview: previewImage,
        base_model: version.base_model || model.base_model,
        trained_words: version.trained_words || [],
        default_version: version.name,
        version_description: version.description || '',
        selectedVersionId: version.id,
        selectedVersionPreviewId,
        size: file.size_kb ? file.size_kb * 1024 : model.size,
        _originalModel: model._originalModel || model,
    };
}
