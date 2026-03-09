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
