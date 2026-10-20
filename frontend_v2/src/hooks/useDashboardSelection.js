import { useState, useCallback } from 'react';
import toast from 'react-hot-toast';
import { filesApi } from '../api';
import { triggerFile } from '../utils/download';
import { refetchNewestGalleryPage } from './useGallery';

export function useDashboardSelection({
    favorites,
    addFavorites,
    queryClient,
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
                const { blob, missingCount } = await filesApi.batchDownload(filesToDownload);
                // `triggerFile` hands the zip Blob over untouched and revokes the
                // object URL a tick later. This used to do it inline, and
                // revoked in the same tick as `link.click()` — which aborts the
                // download in Firefox and older Safari, so the batch silently
                // saved nothing there.
                triggerFile(blob, `comfyui_batch_${Date.now()}.zip`);
                setSelectionMode(false);
                setSelectedFiles(new Set());
                return missingCount;
            })(),
            {
                loading: `Zipping and downloading ${filesToDownload.length} images...`,
                success: (missingCount) => (missingCount > 0
                    ? `Downloaded ${filesToDownload.length - missingCount} images (${missingCount} no longer on disk)`
                    : `Downloaded ${filesToDownload.length} images!`),
                error: (err) => `Download failed: ${err?.message || 'unknown error'}`
            }
        );
    }, [selectedFiles, confirm]);

    // One `addFavorites` call, not a loop of `toggleFavorite`. The favorites
    // endpoint replaces the whole list, so the loop was a read-modify-write
    // race: every iteration read the pre-batch list because `onMutate` had not
    // run yet, N overwrites went to the server, and only the last image
    // survived. The count reported here is now the count actually sent.
    const handleBatchFavorite = useCallback(() => {
        const additions = Array.from(selectedFiles).filter(filename => !favorites.includes(filename));
        if (additions.length === 0) {
            return;
        }
        addFavorites(additions);
        toast.success(`Added ${additions.length} image${additions.length !== 1 ? 's' : ''} to favorites`, { icon: '⭐' });
    }, [favorites, selectedFiles, addFavorites]);

    const handleAddSelectionToCollection = useCallback(() => {
        setShowSelectCollection(true);
    }, [setShowSelectCollection]);

    const handleRemoveSelectionFromCollection = useCallback(async () => {
        if (selectedFiles.size === 0) {
            return;
        }
        if (!activeCollection) {
            toast.error('No collection selected to remove from');
            return;
        }
        const count = selectedFiles.size;
        // Awaited, and the selection only cleared on success. These calls were
        // fired and forgotten with an unconditional success toast, so a rejected
        // PATCH reported a removal that never happened and left the selection
        // looking done.
        //
        // One `removeFromCollection` call carrying the whole selection, not a
        // `Promise.all` over per-image calls. The endpoint takes an `images`
        // array and `Dashboard.jsx` re-wraps whatever it is handed, so the loop
        // was N parallel DELETEs of one element each — 50 selected images meant
        // 50 requests — all sharing one `useMutation` instance, so `isPending`
        // and `error` described whichever of them happened to land last rather
        // than the batch. Same reason as the favorites handler above.
        try {
            await removeFromCollection(activeCollection, Array.from(selectedFiles));
            toast.success(`Removed ${count} image${count !== 1 ? 's' : ''} from collection`);
            setSelectedFiles(new Set());
        } catch {
            // Deliberately silent. The injected `removeFromCollection` is the
            // `useRemoveImagesFromCollection` mutation, whose `onError` reports
            // the failure — so toasting here too showed the user the same error
            // twice for one failure. What this branch owes the user is that the
            // selection survives it: the images are still in the collection, and
            // the selection still says so.
        }
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
            // A DELETION, not an addition: the item is gone, so the whole
            // listing has to be re-read. But a full invalidation of an
            // infinite query refetches EVERY loaded page, one after the
            // other - and a deletion removes one item, usually from the
            // first page.
            await refetchNewestGalleryPage(queryClient);
            setSelectedFiles(new Set());
            setSelectionMode(false);
            toast.success(`Deleted ${selectedFiles.size} images`);
        } catch (e) {
            console.error(e);
            toast.error(`Failed to delete: ${e.message}`);
        }
    }, [queryClient, selectedFiles, confirm]);

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
