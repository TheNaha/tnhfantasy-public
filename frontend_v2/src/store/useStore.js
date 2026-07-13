/**
 * useStore.js - Gallery UI state
 *
 * This store now only tracks the currently active collection in the UI.
 *
 * NOTE: Job state lives in the React Query cache / useActiveJobs hook.
 * File listing is handled by the `useGallery` React Query hook.
 * Collections server data is handled by `useCollections` React Query hook.
 * Favorites server data is handled by `useFavorites` React Query hook.
 * UI preferences (like viewMode) are handled by `settingsStore.js`.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/**
 * Gallery Store
 * Manages UI state, favorites, and activeCollection selection for the gallery.
 * Collections operations have been relocated to useCollections React Query hook.
 */
const useStore = create(
    persist(
        (set) => ({
            activeCollection: null,
            setActiveCollection: (id) => set({ activeCollection: id }),
        }),
        {
            name: 'comfy-storage',
            partialize: (state) => ({
                activeCollection: state.activeCollection,
            }),
        }
    )
);

export default useStore;
