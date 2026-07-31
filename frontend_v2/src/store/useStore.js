/**
 * useStore.js - Gallery UI state
 *
 * This store only tracks the currently active collection in the UI.
 * Server state (Jobs, Gallery files, Collections, Favorites) is handled by React Query hooks.
 * UI layout preferences are handled by settingsStore.js.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/**
 * Gallery Store
 * Manages activeCollection selection for the gallery.
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
