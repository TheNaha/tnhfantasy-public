/**
 * useStore.js - Gallery UI state and collections store
 *
 * Combines several related concerns into one persisted store:
 *
 *   Gallery UI state   – viewMode
 *   Favorites          – local-only list of favorited image filenames
 *   Collections        – server-side albums with local cache and lazy image loading
 *
 * Collections are persisted on the server (see `api/collectionsApi.js`) and
 * automatically migrated from any legacy localStorage data on first load.
 *
 * NOTE: Job state lives in `jobStore.js`; file listing is handled by the
 * `useGallery` React Query hook – this store only tracks UI preferences and
 * collection membership.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import * as collectionsApi from '../api/collectionsApi';

const MIGRATION_KEY = 'comfy-collections-migrated';
const OLD_STORAGE_KEY = 'comfy-storage';

/**
 * Gallery Store
 * Manages UI state, favorites, and collections for the gallery.
 * Collections are now server-side with auto-migration from localStorage.
 * 
 * Note: Jobs handled by jobStore, files by react-query useGallery hook.
 */
const useStore = create(
    persist(
        (set, get) => ({
            // Models state (cached model lists by directory)
            models: {},
            setModels: (directory, models) => set((state) => ({
                models: { ...state.models, [directory]: models },
            })),

            // UI state
            viewMode: 'grid', // 'grid' | 'list' | 'feed' | 'timeline'
            setViewMode: (mode) => set({ viewMode: mode }),

            // Favorites state (still local - simple and fast)
            favorites: [],
            toggleFavorite: (filename) => set((state) => {
                const newFavorites = state.favorites.includes(filename)
                    ? state.favorites.filter(f => f !== filename)
                    : [...state.favorites, filename];
                return { favorites: newFavorites };
            }),
            isFavorite: (filename) => get().favorites.includes(filename),

            // ===============================================
            // Collections state - now server-side
            // ===============================================
            collections: {},
            activeCollection: null,
            collectionsLoading: false,
            collectionsInitialized: false,

            // Initialize collections from server
            initCollections: async () => {
                if (get().collectionsInitialized) return;

                set({ collectionsLoading: true });

                try {
                    // Check for localStorage migration
                    const migrated = localStorage.getItem(MIGRATION_KEY);
                    if (migrated !== 'true') {
                        const oldData = localStorage.getItem(OLD_STORAGE_KEY);
                        if (oldData) {
                            try {
                                const parsed = JSON.parse(oldData);
                                const oldCollections = parsed.state?.collections;

                                if (oldCollections && Object.keys(oldCollections).length > 0) {
                                    console.log('[Store] Migrating', Object.keys(oldCollections).length, 'collections from localStorage');

                                    // Format for API
                                    const collectionsToMigrate = Object.values(oldCollections).map(c => ({
                                        name: c.name || 'Untitled',
                                        color: c.color || '#3B82F6',
                                        description: null,
                                        images: c.images || []
                                    }));

                                    await collectionsApi.importCollections(collectionsToMigrate);
                                    console.log('[Store] Collection migration complete');
                                }

                                localStorage.setItem(MIGRATION_KEY, 'true');
                            } catch (e) {
                                console.warn('[Store] Collection migration failed:', e);
                                localStorage.removeItem(MIGRATION_KEY);
                            }
                        } else {
                            localStorage.setItem(MIGRATION_KEY, 'true');
                        }
                    }

                    // Fetch from server
                    const { collections } = await collectionsApi.listCollections();

                    // Convert array to object keyed by ID
                    const collectionsMap = {};
                    for (const col of collections) {
                        collectionsMap[col.id] = {
                            id: col.id,
                            name: col.name,
                            color: col.color,
                            thumbnail: col.thumbnail,
                            imageCount: col.image_count || 0,
                            images: [], // Loaded on demand
                            created: col.created_at,
                            updated: col.updated_at,
                        };
                    }

                    set({
                        collections: collectionsMap,
                        collectionsLoading: false,
                        collectionsInitialized: true
                    });
                } catch (error) {
                    console.error('[Store] Failed to init collections:', error);
                    set({ collectionsLoading: false, collectionsInitialized: false });
                }
            },

            // Refresh collections from server
            refreshCollections: async () => {
                try {
                    const { collections } = await collectionsApi.listCollections();
                    const collectionsMap = {};
                    for (const col of collections) {
                        collectionsMap[col.id] = {
                            id: col.id,
                            name: col.name,
                            color: col.color,
                            thumbnail: col.thumbnail,
                            imageCount: col.image_count || 0,
                            images: get().collections[col.id]?.images || [],
                            created: col.created_at,
                            updated: col.updated_at,
                        };
                    }
                    set({ collections: collectionsMap });
                } catch (error) {
                    console.error('Failed to refresh collections:', error);
                }
            },

            // Load images for a specific collection
            loadCollectionImages: async (collectionId) => {
                try {
                    const col = await collectionsApi.getCollection(collectionId, true);
                    set((state) => ({
                        collections: {
                            ...state.collections,
                            [collectionId]: {
                                ...state.collections[collectionId],
                                images: col.images || [],
                                imageCount: col.image_count || 0
                            }
                        }
                    }));
                    return col.images;
                } catch (error) {
                    console.error('Failed to load collection images:', error);
                    return [];
                }
            },

            createCollection: async (name, color) => {
                try {
                    const col = await collectionsApi.createCollection({ name, color });
                    set((state) => ({
                        collections: {
                            ...state.collections,
                            [col.id]: {
                                id: col.id,
                                name: col.name,
                                color: col.color || '#3B82F6',
                                thumbnail: null,
                                images: [],
                                imageCount: 0,
                                created: col.created_at,
                                updated: col.updated_at,
                            }
                        }
                    }));
                    return col.id;
                } catch (error) {
                    console.error('Failed to create collection:', error);
                    throw error;
                }
            },

            deleteCollection: async (id) => {
                try {
                    await collectionsApi.deleteCollection(id);
                    set((state) => {
                        const newCollections = { ...state.collections };
                        delete newCollections[id];
                        return {
                            collections: newCollections,
                            activeCollection: state.activeCollection === id ? null : state.activeCollection
                        };
                    });
                } catch (error) {
                    console.error('Failed to delete collection:', error);
                    throw error;
                }
            },

            renameCollection: async (id, name) => {
                try {
                    await collectionsApi.updateCollection(id, { name });
                    set((state) => ({
                        collections: {
                            ...state.collections,
                            [id]: { ...state.collections[id], name, updated: new Date().toISOString() }
                        }
                    }));
                } catch (error) {
                    console.error('Failed to rename collection:', error);
                    throw error;
                }
            },

            addToCollection: async (collectionId, images) => {
                try {
                    await collectionsApi.addImagesToCollection(collectionId, images);
                    set((state) => {
                        const collection = state.collections[collectionId];
                        if (!collection) return state;
                        const newImages = [...new Set([...collection.images, ...images])];
                        return {
                            collections: {
                                ...state.collections,
                                [collectionId]: {
                                    ...collection,
                                    images: newImages,
                                    imageCount: newImages.length,
                                    updated: new Date().toISOString(),
                                    thumbnail: newImages[0] || null
                                }
                            }
                        };
                    });
                } catch (error) {
                    console.error('Failed to add to collection:', error);
                    throw error;
                }
            },

            removeFromCollection: async (collectionId, images) => {
                try {
                    await collectionsApi.removeImagesFromCollection(collectionId, images);
                    set((state) => {
                        const collection = state.collections[collectionId];
                        if (!collection) return state;
                        const newImages = collection.images.filter(img => !images.includes(img));
                        return {
                            collections: {
                                ...state.collections,
                                [collectionId]: {
                                    ...collection,
                                    images: newImages,
                                    imageCount: newImages.length,
                                    updated: new Date().toISOString(),
                                    thumbnail: newImages[0] || null
                                }
                            }
                        };
                    });
                } catch (error) {
                    console.error('Failed to remove from collection:', error);
                    throw error;
                }
            },

            setActiveCollection: (id) => set({ activeCollection: id }),

            // Pagination state (for infinite scroll tracking)
            page: 0,
            hasMore: true,
            setPage: (page) => set({ page }),
            setHasMore: (hasMore) => set({ hasMore }),
            resetPagination: () => set({ page: 0, hasMore: true }),
        }),
        {
            name: 'comfy-storage',
            partialize: (state) => ({
                viewMode: state.viewMode,
                favorites: state.favorites,
                activeCollection: state.activeCollection,
                // Collections no longer persisted locally - server-side now
            }),
        }
    )
);

export default useStore;
