/**
 * useFiles Hook
 * Provides file operations using the centralized API.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { filesApi } from '../api';
import toast from 'react-hot-toast';

export function useFiles() {
    const queryClient = useQueryClient();

    const deleteMutation = useMutation({
        mutationFn: (filename) => filesApi.delete(filename),
        onSuccess: (_, filename) => {
            queryClient.invalidateQueries({ queryKey: ['gallery'] });
            toast.success(`Deleted ${filename}`, { icon: '🗑️' });
        },
        onError: (error) => {
            toast.error(`Failed to delete: ${error.message}`);
        },
    });

    const batchDeleteMutation = useMutation({
        mutationFn: (filenames) => filesApi.deleteMultiple(filenames),
        onSuccess: (_, filenames) => {
            queryClient.invalidateQueries({ queryKey: ['gallery'] });
            toast.success(`Deleted ${filenames.length} files`, { icon: '🗑️' });
        },
        onError: (error) => {
            toast.error(`Failed to delete: ${error.message}`);
        },
    });

    return {
        deleteFile: deleteMutation.mutate,
        deleteFiles: batchDeleteMutation.mutate,
        isDeleting: deleteMutation.isPending || batchDeleteMutation.isPending,
        // URL helpers
        getFileUrl: filesApi.getUrl,
        getThumbnailUrl: filesApi.getThumbnailUrl,
    };
}

export default useFiles;
