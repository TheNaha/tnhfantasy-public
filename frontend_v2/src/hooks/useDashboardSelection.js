import { useState, useCallback } from 'react';
import toast from 'react-hot-toast';
import { filesApi } from '../api';

export function useDashboardSelection({ 
    favorites, 
    toggleFavorite, 
    queryClient, 
    filters,
    confirm,
    activeCollection,
    removeFromCollection,
    setShowSelectCollection
}) {
    const [selectionMode, setSelectionMode] = useState(false);
    const [selectedFiles, setSelectedFiles] = useState(new Set());

    const toggleSelection = useCallback((filename) => {
        setSelectedFiles(prev => {
            const newSet = new Set(prev);
            if (newSet.has(filename)) newSet.delete(filename);
            else newSet.add(filename);
            return newSet;
        });
    }, []);

    const handleBatchDownload = useCallback(async () => {
        const accepted = await confirm({
            title: 'Download Images',
            message: `Download ${selectedFiles.size} images to your computer?`,
            confirmText: 'Download',
        });
        if (!accepted) return;
        const filesToDownload = Array.from(selectedFiles);
        toast.promise(
            (async () => {
                const blob = await filesApi.batchDownload(filesToDownload);
                const url = window.URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = `comfyui_batch_${Date.now()}.zip`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                window.URL.revokeObjectURL(url);
            })(),
            {
                loading: `Zipping and downloading ${filesToDownload.length} images...`,
                success: `Downloaded ${filesToDownload.length} images!`,
                error: 'Download failed'
            }
        );
        setSelectionMode(false);
        setSelectedFiles(new Set());
    }, [selectedFiles, confirm]);

    const handleBatchFavorite = useCallback(() => {
        let addedCount = 0;
        Array.from(selectedFiles).forEach(filename => {
            if (!favorites.includes(filename)) {
                toggleFavorite(filename);
                addedCount += 1;
            }
        });
        if (addedCount > 0) {
            toast.success(`Added ${addedCount} image${addedCount !== 1 ? 's' : ''} to favorites`, { icon: '⭐' });
        }
    }, [favorites, selectedFiles, toggleFavorite]);

    const handleAddSelectionToCollection = useCallback(() => {
        setShowSelectCollection(true);
    }, [setShowSelectCollection]);

    const handleRemoveSelectionFromCollection = useCallback(() => {
        if (selectedFiles.size === 0) {
            return;
        }
        if (!activeCollection) {
            toast.error('No collection selected to remove from');
            return;
        }
        selectedFiles.forEach(filename => {
            removeFromCollection(activeCollection, filename);
        });
        toast.success(`Removed ${selectedFiles.size} image${selectedFiles.size !== 1 ? 's' : ''} from collection`);
        setSelectedFiles(new Set());
    }, [activeCollection, removeFromCollection, selectedFiles]);

    const handleBatchDelete = useCallback(async () => {
        const accepted = await confirm({
            title: `Delete ${selectedFiles.size} Images`,
            message: 'Are you sure you want to delete these images? This action cannot be undone.',
            confirmText: 'Delete Images',
            isDangerous: true,
        });
        if (!accepted) return;
        try {
            await filesApi.deleteMultiple(Array.from(selectedFiles));
            queryClient.invalidateQueries({ queryKey: ['gallery', filters], exact: true });
            setSelectedFiles(new Set());
            setSelectionMode(false);
            toast.success(`Deleted ${selectedFiles.size} images`);
        } catch (e) {
            console.error(e);
            toast.error(`Failed to delete: ${e.message}`);
        }
    }, [queryClient, selectedFiles, filters, confirm]);

    const handleCancelSelectionMode = useCallback(() => {
        setSelectionMode(false);
        setSelectedFiles(new Set());
    }, []);

    return {
        selectionMode,
        setSelectionMode,
        selectedFiles,
        setSelectedFiles,
        toggleSelection,
        handleBatchDownload,
        handleBatchFavorite,
        handleAddSelectionToCollection,
        handleRemoveSelectionFromCollection,
        handleBatchDelete,
        handleCancelSelectionMode,
    };
}
