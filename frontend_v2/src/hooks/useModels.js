import { useState, useEffect } from 'react';
import toast from 'react-hot-toast';
import { filesApi } from '../api';

const MODEL_REQUESTS = [
    { key: 'checkpoints', directory: 'models/checkpoints', label: 'checkpoints' },
    { key: 'controlNetModels', directory: 'models/controlnet', label: 'controlnet models' },
    { key: 'upscalerModels', directory: 'models/upscale_models', label: 'upscaler models' },
    { key: 'adetailerModels', directory: 'models/ultralytics/bbox', label: 'adetailer models' },
    { key: 'vaeModels', directory: 'models/vae', label: 'VAE models' },
    { key: 'embeddingModels', directory: 'models/embeddings', label: 'embedding models' },
    { key: 'loraModels', directory: 'models/loras', label: 'LoRA models' }
];

async function loadModelDirectories() {
    const results = await Promise.allSettled(
        MODEL_REQUESTS.map(({ directory }) => filesApi.list({ directory }))
    );

    const data = {};
    const failures = [];

    results.forEach((result, index) => {
        const request = MODEL_REQUESTS[index];
        if (result.status === 'fulfilled') {
            data[request.key] = result.value.files || [];
            return;
        }

        data[request.key] = [];
        failures.push({
            directory: request.directory,
            label: request.label,
            reason: result.reason?.message || 'Unknown error'
        });
    });

    return { data, failures };
}

/**
 * Hook for loading all available models from the backend.
 * Centralizes model fetching logic used by SimpleGenerator and other components.
 */
export function useModels() {
    const [checkpoints, setCheckpoints] = useState([]);
    const [controlNetModels, setControlNetModels] = useState([]);
    const [upscalerModels, setUpscalerModels] = useState([]);
    const [vaeModels, setVaeModels] = useState([]);
    const [embeddingModels, setEmbeddingModels] = useState([]);
    const [adetailerModels, setAdetailerModels] = useState([]);
    const [loraModels, setLoraModels] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const applyModelState = (modelData) => {
        setCheckpoints(modelData.checkpoints || []);
        setControlNetModels(modelData.controlNetModels || []);
        setUpscalerModels(modelData.upscalerModels || []);
        setVaeModels(modelData.vaeModels || []);
        setEmbeddingModels(modelData.embeddingModels || []);
        setAdetailerModels(modelData.adetailerModels || []);
        setLoraModels(modelData.loraModels || []);
    };

    const buildFailureMessage = (failures) => {
        if (failures.length === 0) {
            return null;
        }

        if (failures.length === MODEL_REQUESTS.length) {
            return 'Failed to load any model directories';
        }

        return `Some model directories failed to load: ${failures.map(failure => failure.label).join(', ')}`;
    };

    useEffect(() => {
        const loadModels = async () => {
            setLoading(true);
            setError(null);

            try {
                const { data, failures } = await loadModelDirectories();
                applyModelState(data);

                const failureMessage = buildFailureMessage(failures);
                if (failureMessage) {
                    console.warn('[useModels] Partial model load failure', failures);
                    setError(failureMessage);
                    toast.error(failureMessage);
                }
            } catch (e) {
                console.error("Failed to load models", e);
                setError(e.message);
                toast.error("Failed to load models");
            } finally {
                setLoading(false);
            }
        };

        loadModels();
    }, []);

    const refresh = async () => {
        setLoading(true);
        try {
            setError(null);
            const { data, failures } = await loadModelDirectories();
            applyModelState(data);

            const failureMessage = buildFailureMessage(failures);
            if (failureMessage) {
                console.warn('[useModels] Partial model refresh failure', failures);
                setError(failureMessage);
                toast.error(failureMessage);
            } else {
                toast.success("Models refreshed");
            }
        } catch (e) {
            setError(e.message);
            toast.error("Failed to refresh models");
        } finally {
            setLoading(false);
        }
    };

    return {
        // Model lists
        checkpoints,
        controlNetModels,
        upscalerModels,
        vaeModels,
        embeddingModels,
        adetailerModels,
        loraModels,

        // Status
        loading,
        error,

        // Actions
        refresh
    };
}
