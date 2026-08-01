/**
 * settingsStore.js - Persistent UI preferences store
 *
 * Backed by localStorage via Zustand's `persist` middleware so settings
 * survive page refreshes.  Settings are grouped into logical categories:
 *
 *   ui        – Global UI behaviour (view mode, animation speed, React Query
 *               cache timings, toast durations).
 *   gallery   – Output image gallery display preferences.
 *   models    – Model Manager behaviour (sync, auto-remove after download).
 *   generator – Generation page convenience options (seed randomisation,
 *               post-generation redirect).
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/**
 * Default values for all settings.
 * These are merged with any values already persisted in localStorage,
 * so new keys added here will be picked up on the next page load.
 */
const DEFAULT_SETTINGS = {
    ui: {
        defaultViewMode: 'grid',    // 'grid' | 'list'
        defaultGridColumns: 4,       // columns shown in grid view
        toastDuration: 3000,         // default toast lifetime (ms)
        toastSuccessDuration: 3000,  // success toast lifetime (ms)
        toastErrorDuration: 4000,    // error toast lifetime (ms) – slightly longer so users can read it
        animationDuration: 200,      // CSS transition / Framer Motion default (ms)
        queryStaleTime: 300000,      // React Query: how long before data is considered stale (5 min)
        queryCacheTime: 600000       // React Query: how long unused cached data is kept (10 min)
    },
    gallery: {
        itemsPerPage: 20,            // images per page in the gallery
        autoRefreshOnJobComplete: true,  // refresh gallery when a generation finishes
        silentRefresh: true          // refresh without showing a loading spinner
    },
    models: {
        itemsPerPage: 20,            // models shown per page in Model Manager
        autoRemoveDownloads: true    // remove download records after they complete
    },
    generator: {
        autoRandomizeSeed: true,     // randomise seed before each generation
        redirectAfterGenerate: true, // navigate to dashboard after submitting a job
        redirectDelay: 1000          // delay before redirect (ms) – lets the user see the job appear
    },
    ai: {
        defaultProviderId: null,  // null = auto-detect
        defaultModelId: null,     // null = auto-detect  
        lorebookInjectionMode: 'system_prompt',  // 'system_prompt' | 'messages'
        temperature: 0.8,
        maxContextTokens: 4096,
    }
};

const useSettingsStore = create(
    persist(
        (set, get) => ({
            settings: DEFAULT_SETTINGS,

            /**
             * Update a single setting within a category.
             *
             * @param {string} category - Top-level settings group (e.g. 'ui', 'gallery').
             * @param {string} key      - Setting key within the category.
             * @param {*}      value    - New value to assign.
             *
             * @example
             * updateSetting('ui', 'defaultViewMode', 'list');
             */
            updateSetting: (category, key, value) => {
                set((state) => ({
                    settings: {
                        ...state.settings,
                        [category]: {
                            ...state.settings[category],
                            [key]: value
                        }
                    }
                }));
            },

            /**
             * Update multiple settings at once using a nested updates object.
             * Only existing categories are updated; unknown categories are ignored.
             *
             * @param {object} updates - Partial settings object, e.g.
             *   { ui: { defaultGridColumns: 3 }, gallery: { itemsPerPage: 40 } }
             */
            updateSettings: (updates) => {
                set((state) => {
                    const newSettings = { ...state.settings };
                    Object.keys(updates).forEach(category => {
                        if (newSettings[category]) {
                            newSettings[category] = {
                                ...newSettings[category],
                                ...updates[category]
                            };
                        }
                    });
                    return { settings: newSettings };
                });
            },

            /**
             * Reset all settings to their compiled-in defaults.
             * This also clears any values that were persisted in localStorage.
             */
            resetSettings: () => {
                set({ settings: DEFAULT_SETTINGS });
            },

            /**
             * Reset a single settings category to its default values.
             *
             * @param {string} category - Category to reset (e.g. 'ui', 'models').
             */
            resetCategory: (category) => {
                set((state) => ({
                    settings: {
                        ...state.settings,
                        [category]: DEFAULT_SETTINGS[category]
                    }
                }));
            },

            /**
             * Read a single setting value.
             *
             * @param {string} category - Top-level settings group.
             * @param {string} key      - Setting key within the category.
             * @returns {*} The current value, or `undefined` if the key doesn't exist.
             */
            getSetting: (category, key) => {
                return get().settings[category]?.[key];
            }
        }),
        {
            // localStorage key – must be unique across all persisted stores
            name: 'comfyui-settings-storage',
            version: 1
        }
    )
);

export default useSettingsStore;

/**
 * Convenience hook that returns just the settings object (read-only).
 *
 * @returns {object} Current settings – reactive, triggers re-renders on change.
 *
 * @example
 * const settings = useSettings();
 * const columns = settings.ui.defaultGridColumns;
 */
export const useSettings = () => {
    const settings = useSettingsStore((state) => state.settings);
    return settings;
};

/**
 * Convenience hook that returns settings mutation helpers.
 * Unlike `useSettings`, this does NOT cause re-renders when settings change,
 * because it only selects the action functions (which are stable references).
 *
 * @returns {{ updateSetting, updateSettings, resetSettings, resetCategory }}
 */
export const useUpdateSettings = () => {
    const updateSetting = useSettingsStore((state) => state.updateSetting);
    const updateSettings = useSettingsStore((state) => state.updateSettings);
    const resetSettings = useSettingsStore((state) => state.resetSettings);
    const resetCategory = useSettingsStore((state) => state.resetCategory);

    return {
        updateSetting,
        updateSettings,
        resetSettings,
        resetCategory
    };
};
