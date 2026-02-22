import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// Default settings
const DEFAULT_SETTINGS = {
    ui: {
        defaultViewMode: 'grid',
        defaultGridColumns: 4,
        toastDuration: 3000,
        toastSuccessDuration: 3000,
        toastErrorDuration: 4000,
        animationDuration: 200,
        queryStaleTime: 300000,  // 5 minutes
        queryCacheTime: 600000   // 10 minutes
    },
    gallery: {
        itemsPerPage: 20,
        autoRefreshOnJobComplete: true,
        silentRefresh: true
    },
    models: {
        itemsPerPage: 20,
        autoSync: true,
        autoRemoveDownloads: true
    },
    generator: {
        autoRandomizeSeed: true,
        redirectAfterGenerate: true,
        redirectDelay: 1000
    }
};

const useSettingsStore = create(
    persist(
        (set, get) => ({
            settings: DEFAULT_SETTINGS,

            // Update a specific setting
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

            // Update multiple settings at once
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

            // Reset all settings to defaults
            resetSettings: () => {
                set({ settings: DEFAULT_SETTINGS });
            },

            // Reset a specific category
            resetCategory: (category) => {
                set((state) => ({
                    settings: {
                        ...state.settings,
                        [category]: DEFAULT_SETTINGS[category]
                    }
                }));
            },

            // Get a specific setting value
            getSetting: (category, key) => {
                return get().settings[category]?.[key];
            }
        }),
        {
            name: 'comfyui-settings-storage',
            version: 1
        }
    )
);

export default useSettingsStore;

// Hook for easier access
export const useSettings = () => {
    const settings = useSettingsStore((state) => state.settings);
    return settings;
};

// Hook for updating settings
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
