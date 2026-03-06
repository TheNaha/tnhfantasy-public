import { useState, useEffect } from 'react';
import toast from 'react-hot-toast';
import { filesApi } from '../api';

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

    useEffect(() => {
        const loadModels = async () => {
            setLoading(true);
            setError(null);

            try {
                const [ckptData, cnData, upData, adData, vaeData, embData, loraData] = await Promise.all([
                    filesApi.list({ directory: 'models/checkpoints' }),
                    filesApi.list({ directory: 'models/controlnet' }),
                    filesApi.list({ directory: 'models/upscale_models' }),
                    filesApi.list({ directory: 'models/ultralytics/bbox' }),
                    filesApi.list({ directory: 'models/vae' }),
                    filesApi.list({ directory: 'models/embeddings' }),
                    filesApi.list({ directory: 'models/loras' })
                ]);

                setCheckpoints(ckptData.files || []);
                setControlNetModels(cnData.files || []);
                setUpscalerModels(upData.files || []);
                setAdetailerModels(adData.files || []);
                setVaeModels(vaeData.files || []);
                setEmbeddingModels(embData.files || []);
                setLoraModels(loraData.files || []);
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
            const [ckptData, cnData, upData, adData, vaeData, embData, loraData] = await Promise.all([
                filesApi.list({ directory: 'models/checkpoints' }),
                filesApi.list({ directory: 'models/controlnet' }),
                filesApi.list({ directory: 'models/upscale_models' }),
                filesApi.list({ directory: 'models/ultralytics/bbox' }),
                filesApi.list({ directory: 'models/vae' }),
                filesApi.list({ directory: 'models/embeddings' }),
                filesApi.list({ directory: 'models/loras' })
            ]);

            setCheckpoints(ckptData.files || []);
            setControlNetModels(cnData.files || []);
            setUpscalerModels(upData.files || []);
            setAdetailerModels(adData.files || []);
            setVaeModels(vaeData.files || []);
            setEmbeddingModels(embData.files || []);
            setLoraModels(loraData.files || []);
            toast.success("Models refreshed");
        } catch {
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
