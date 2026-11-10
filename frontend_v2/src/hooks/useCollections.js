import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import {
    listCollections, getCollection, createCollection, deleteCollection,
    updateCollection, addImagesToCollection, removeImagesFromCollection,
    importCollections, moveImagesBetweenCollections
} from '../api/collectionsApi';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { reportError } from './useWorldVaultResource';
import useStore from '../store/useStore';

const MIGRATION_KEY = 'comfy-collections-migrated';
const OLD_STORAGE_KEY = 'comfy-storage';

// Invalidates every workspace-scoped collections query. The list endpoint is
// keyed by workspace ('image' | 'chat' | 'story' | null), so a mutation must
// clear all variants, not just the prefix or the null-scope one.
function invalidateAllCollections(queryClient) {
    queryClient.invalidateQueries({ queryKey: ['collections'] });
    // A character's collection membership is a *second* server entity read
    // under `buildQueryKey(QUERY_KEYS.CHARACTERS, id, 'collection')`
    // (GET /api/v2/collections/by-character/:id), rendered by
    // `ChatContextPanel`. Only one call site in the app remembered to refresh
    // it, and it did so by hand, so every other add/remove left the chat panel
    // showing the membership from before the edit. The query is mounted for the
    // life of the chat and `refetchOnWindowFocus` is globally off, so nothing
    // corrected it later. Invalidate the character list instead: that is the
    // prefix the detail key lives under, so it covers the per-id variant too.
    queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
}

// One-time bootstrap migration: imports collections from the legacy
// pre-API localStorage store. Runs once per page load from App.jsx —
// deliberately NOT inside the query function, so the (already-completed)
// migration can't re-trigger on every collection refetch.
export async function migrateLegacyCollections() {
    const migrated = localStorage.getItem(MIGRATION_KEY);
    if (migrated === 'true' || migrated === 'failed') return;

    const oldData = localStorage.getItem(OLD_STORAGE_KEY);
    if (!oldData) {
        localStorage.setItem(MIGRATION_KEY, 'true');
        return;
    }

    try {
        const parsed = JSON.parse(oldData);
        const oldCollections = parsed.state?.collections;

        if (oldCollections && Object.keys(oldCollections).length > 0) {
            const collectionsToMigrate = Object.values(oldCollections).map(c => ({
                name: c.name || 'Untitled',
                color: c.color || '#3B82F6',
                description: null,
                images: c.images || []
            }));
            await importCollections(collectionsToMigrate);
        }
        localStorage.setItem(MIGRATION_KEY, 'true');
    } catch (e) {
        console.warn('[Store] Collection migration failed:', e);
        localStorage.setItem(MIGRATION_KEY, 'failed');
    }
}

export function useCollections(workspace = null) {
    return useQuery({
        queryKey: ['collections', workspace],
        queryFn: async ({ signal }) => {
            const { collections } = await listCollections(workspace, { signal });
            // Convert to collections map keyed by id to be compatible with older store design
            const collectionsMap = {};
            for (const col of collections) {
                collectionsMap[col.id] = {
                    id: col.id,
                    name: col.name,
                    color: col.color,
                    thumbnail: col.thumbnail,
                    imageCount: col.image_count || 0,
                    images: [], // lazy hydration
                    created: col.created_at,
                    updated: col.updated_at,
                };
            }
            return collectionsMap;
        },
        staleTime: 5 * 60 * 1000, // 5 minutes
    });
}

export function useCollectionImages(collectionId) {
    return useQuery({
        queryKey: ['collections', collectionId, 'images'],
        queryFn: async ({ signal }) => {
            if (!collectionId) return [];
            const col = await getCollection(collectionId, true, { signal });
            return col.images || [];
        },
        enabled: !!collectionId,
        staleTime: 5 * 60 * 1000,
    });
}

export function useCreateCollection() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ name, color, workspace }) => {
            return createCollection({ name, color, workspace });
        },
        onSuccess: () => {
            invalidateAllCollections(queryClient);
        },
        onError: (error) => reportError('create collection', error),
    });
}

export function useDeleteCollection() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id) => {
            return deleteCollection(id);
        },
        onSuccess: (_data, id) => {
            const currentActive = useStore.getState().activeCollection;
            if (currentActive === id) {
                useStore.getState().setActiveCollection(null);
            }
            invalidateAllCollections(queryClient);
        },
        onError: (error) => reportError('delete collection', error),
    });
}

export function useRenameCollection() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, name }) => {
            return updateCollection(id, { name });
        },
        onSuccess: () => {
            invalidateAllCollections(queryClient);
        },
        onError: (error) => reportError('rename collection', error),
    });
}

export function useAddImagesToCollection() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ collectionId, images }) => {
            return addImagesToCollection(collectionId, images);
        },
        onSuccess: (_, { collectionId }) => {
            invalidateAllCollections(queryClient);
            queryClient.invalidateQueries({ queryKey: ['collections', collectionId, 'images'] });
        },
        onError: (error) => reportError('add images to collection', error),
    });
}

export function useRemoveImagesFromCollection() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ collectionId, images }) => {
            return removeImagesFromCollection(collectionId, images);
        },
        onSuccess: (_, { collectionId }) => {
            invalidateAllCollections(queryClient);
            queryClient.invalidateQueries({ queryKey: ['collections', collectionId, 'images'] });
        },
        // One error path for every caller. There was only `onSuccess`, so the
        // only way a failed removal was ever seen was a caller remembering to
        // wrap `mutateAsync` — and a caller that did not got a rejected promise
        // with nothing attached: the collection list stayed stale, the selected
        // images stayed selected, and the user saw a button do nothing. React
        // Query runs this for `mutate` as well as `mutateAsync`, so a
        // fire-and-forget call site can no longer fail silently.
        onError: (error) => {
            console.error('[Collections] remove images failed:', error);
            toast.error('Failed to remove images from collection');
        },
    });
}

export function useMoveImagesBetweenCollections() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ fromCollectionId, toCollectionId, images }) => {
            return moveImagesBetweenCollections(fromCollectionId, toCollectionId, images);
        },
        onSuccess: (_, { fromCollectionId, toCollectionId }) => {
            invalidateAllCollections(queryClient);
            queryClient.invalidateQueries({ queryKey: ['collections', fromCollectionId, 'images'] });
            queryClient.invalidateQueries({ queryKey: ['collections', toCollectionId, 'images'] });
        },
        onError: (error) => reportError('move images between collections', error),
    });
}
