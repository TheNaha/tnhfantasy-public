import { useCallback } from 'react';
import toast from 'react-hot-toast';
import { api } from '../api';
import { useGeneratorStore } from '../store/generatorStore';

/**
 * Hook for handling ControlNet operations.
 * Provides handlers for adding, removing, updating ControlNets and uploading images.
 */
export function useControlNet(controlNetModels = []) {
    const { controlnets, addControlNet, removeControlNet, updateControlNet } = useGeneratorStore();

    const handleAdd = useCallback(() => {
        const defaultModel = controlNetModels[0]?.name;
        addControlNet(defaultModel);
    }, [controlNetModels, addControlNet]);

    const handleRemove = useCallback((index) => {
        removeControlNet(index);
    }, [removeControlNet]);

    const handleChange = useCallback((index, field, value) => {
        updateControlNet(index, field, value);
    }, [updateControlNet]);

    const handleUpload = useCallback(async (index, file) => {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('path', 'input');

        const uploadPromise = api.post('/api/upload', formData);

        toast.promise(uploadPromise, {
            loading: 'Uploading image...',
            success: (data) => {
                if (data.status === 'success') {
                    updateControlNet(index, 'image', file.name);
                    return 'Image uploaded!';
                } else {
                    throw new Error('Upload failed');
                }
            },
            error: 'Upload failed'
        });
    }, [updateControlNet]);

    return {
        controlnets,
        handleAdd,
        handleRemove,
        handleChange,
        handleUpload
    };
}

/**
 * Hook for handling LoRA operations.
 * Provides handlers for adding, removing, updating LoRAs and trigger words.
 */
export function useLoras() {
    const { selectedLoras, addLora, removeLora, updateLora, addTriggerWords } = useGeneratorStore();

    const handleAdd = useCallback(() => {
        addLora();
    }, [addLora]);

    const handleRemove = useCallback((index) => {
        removeLora(index);
    }, [removeLora]);

    const handleChange = useCallback((index, field, value) => {
        updateLora(index, field, value);
    }, [updateLora]);

    const handleAddTriggerWords = useCallback((words) => {
        addTriggerWords(words);
        toast.success("Added trigger words!");
    }, [addTriggerWords]);

    return {
        loras: selectedLoras,
        handleAdd,
        handleRemove,
        handleChange,
        handleAddTriggerWords
    };
}
