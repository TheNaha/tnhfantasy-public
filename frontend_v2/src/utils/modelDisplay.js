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
