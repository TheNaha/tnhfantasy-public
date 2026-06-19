import { useState, useCallback } from 'react';
import toast from 'react-hot-toast';
import { filesApi } from '../api';

export function useDashboardSelection({ 
    favorites, 
    toggleFavorite, 
    queryClient, 
    filters,
    setConfirmModal,
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

    const handleBatchDownload = useCallback(() => {
        setConfirmModal({
            isOpen: true,
            title: 'Download Images',
            message: `Download ${selectedFiles.size} images to your computer?`,
            isDangerous: false,
            confirmText: 'Download',
            onConfirm: async () => {
                const filesToDownload = Array.from(selectedFiles);
                toast.promise(
                    (async () => {
                        for (const filename of filesToDownload) {
                            const link = document.createElement('a');
                            link.href = `/api/view/output/${filename}`;
                            link.download = filename;
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                            await new Promise(resolve => setTimeout(resolve, 500));
                        }
                    })(),
                    {
                        loading: `Downloading ${filesToDownload.length} images...`,
                        success: `Downloaded ${filesToDownload.length} images!`,
                        error: 'Download failed'
                    }
                );
                setSelectionMode(false);
                setSelectedFiles(new Set());
            }
        });
    }, [selectedFiles, setConfirmModal]);

    const handleBatchFavorite = useCallback(() => {
        Array.from(selectedFiles).forEach(filename => {
            if (!favorites.includes(filename)) {
                toggleFavorite(filename);
            }
        });
        toast.success(`Added ${selectedFiles.size} images to favorites`, { icon: '⭐' });
    }, [favorites, selectedFiles, toggleFavorite]);

    const handleAddSelectionToCollection = useCallback(() => {
        setShowSelectCollection(true);
    }, [setShowSelectCollection]);

    const handleRemoveSelectionFromCollection = useCallback(() => {
        selectedFiles.forEach(filename => {
            removeFromCollection(activeCollection, filename);
        });
        toast.success(`Removed ${selectedFiles.size} images from collection`);
        setSelectedFiles(new Set());
    }, [activeCollection, removeFromCollection, selectedFiles]);

    const handleBatchDelete = useCallback(() => {
        setConfirmModal({
            isOpen: true,
            title: `Delete ${selectedFiles.size} Images`,
            message: 'Are you sure you want to delete these images? This action cannot be undone.',
            isDangerous: true,
            confirmText: 'Delete Images',
            onConfirm: async () => {
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
            }
        });
    }, [queryClient, selectedFiles, filters, setConfirmModal]);

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
