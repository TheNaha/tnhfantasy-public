import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import collectionsApi from '../api/collectionsApi';

const MIGRATION_KEY = 'comfy-collections-migrated';
const OLD_STORAGE_KEY = 'comfy-storage';

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
            await collectionsApi.importCollections(collectionsToMigrate);
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
        queryFn: async () => {
            const { collections } = await collectionsApi.listCollections(workspace);
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
        queryFn: async () => {
            if (!collectionId) return [];
            const col = await collectionsApi.getCollection(collectionId, true);
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
            return collectionsApi.createCollection({ name, color, workspace });
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['collections'] });
            queryClient.invalidateQueries({ queryKey: ['collections', null] });
        }
    });
}

export function useDeleteCollection() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id) => {
            return collectionsApi.deleteCollection(id);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['collections'] });
            queryClient.invalidateQueries({ queryKey: ['collections', null] });
        }
    });
}

export function useRenameCollection() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, name }) => {
            return collectionsApi.updateCollection(id, { name });
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['collections'] });
            queryClient.invalidateQueries({ queryKey: ['collections', null] });
        }
    });
}

export function useAddImagesToCollection() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ collectionId, images }) => {
            return collectionsApi.addImagesToCollection(collectionId, images);
        },
        onSuccess: (_, { collectionId }) => {
            queryClient.invalidateQueries({ queryKey: ['collections'] });
            queryClient.invalidateQueries({ queryKey: ['collections', null] });
            queryClient.invalidateQueries({ queryKey: ['collections', collectionId, 'images'] });
        }
    });
}

export function useRemoveImagesFromCollection() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ collectionId, images }) => {
            return collectionsApi.removeImagesFromCollection(collectionId, images);
        },
        onSuccess: (_, { collectionId }) => {
            queryClient.invalidateQueries({ queryKey: ['collections'] });
            queryClient.invalidateQueries({ queryKey: ['collections', null] });
            queryClient.invalidateQueries({ queryKey: ['collections', collectionId, 'images'] });
        }
    });
}
