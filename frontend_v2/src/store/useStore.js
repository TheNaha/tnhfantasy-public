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
 * NOTE: Job state lives in the React Query cache / useActiveJobs hook; file listing is handled by the
 * `useGallery` React Query hook – this store only tracks UI preferences and
 * collection membership.
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
        (set, get) => ({
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
