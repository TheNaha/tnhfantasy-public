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

/**
 * The gallery view modes a user can *choose* as their default, in menu order.
 *
 * This exists because three files had three vocabularies. `Settings.jsx`
 * offered grid/list/feed, `DashboardHeader` toggled grid/list/feed/timeline,
 * and `Dashboard` toggled grid/session — all three writing the same
 * `ui.defaultViewMode` key. Two consequences, both measured on the live stack:
 * `timeline` and `session` were writable with no matching `<option>`, so a
 * `<select value="session">` rendered blank, and picking any value from it
 * silently switched the gallery out of the session view the user was in; and
 * the "default" was overwritten by the first gallery interaction of every
 * session, so the setting could not describe a default at all.
 *
 * `SESSION_VIEW_MODE` is deliberately absent: the session panel is an
 * alternate live view reached by a toggle, not something to land on by default.
 */
export const GALLERY_VIEW_MODES = ['grid', 'list', 'feed', 'timeline'];
export const SESSION_VIEW_MODE = 'session';

const DEFAULT_SETTINGS = {
    ui: {
        defaultViewMode: 'grid',    // one of GALLERY_VIEW_MODES
        defaultGridColumns: 4,       // columns shown in grid view
        // The live gallery view, written by every in-page view toggle and read
        // only by the Dashboard. `null` means "follow defaultViewMode", which is
        // what a user who has never toggled gets — and what every existing
        // install gets on upgrade, since this key is new.
        viewMode: null,
        gridColumns: null,           // live column count; null = follow the default
        toastSuccessDuration: 3000,  // success toast lifetime (ms)
        toastErrorDuration: 4000,    // error toast lifetime (ms) – slightly longer so users can read it
        animationDuration: 200,      // Framer Motion default transition (ms)
        queryStaleTime: 300000,      // React Query: how long before data is considered stale (5 min)
        queryCacheTime: 600000       // React Query: how long unused cached data is kept (10 min)
    },
    gallery: {
        itemsPerPage: 20,            // images per page in the gallery
        autoRefreshOnJobComplete: true,  // refresh gallery when a generation finishes
        silentRefresh: true          // refresh without showing a loading spinner
    },
    models: {
        itemsPerPage: 20             // models shown per page in Model Manager
        // `autoRemoveDownloads` was removed with its Settings switch. It had no
        // reader anywhere; the backend's equivalent is
        // `downloads.auto_remove_delay` in config.json. See
        // src/test/settingsKeysHaveReaders.test.js for the guard.
    },
    generator: {
        autoRandomizeSeed: true,     // randomise seed before each generation
        redirectAfterGenerate: true, // navigate to dashboard after submitting a job
        redirectDelay: 1000,         // delay before redirect (ms) – lets the user see the job appear
        // Prompt shortcut tokens (e.g. `lazypos`) expanded by the backend before
        // dispatching to ComfyUI. Mirror of config.json `generator.prompt_shortcuts`.
        // Seeded from server config on the Settings page; users do not edit this.
        prompt_shortcuts: {},
        // MIRROR of config.json `generator.default_checkpoint`, not a second
        // source of truth. The Settings page reads and writes the server value
        // through PUT /api/settings and seeds this from it, because
        // ChatWorkspaceContext sends it per message as `generator_checkpoint`.
        // It used to be written only to localStorage while the backend read
        // config.json, so the control changed nothing.
        defaultCheckpoint: null,
        batchPresets: {}             // custom batch generation presets: { name: { preset, basePrompt, charName, sceneName, seedMode, negativePrompt, sizeKey, steps } }
    },
    ai: {
        // Wired to backend config (config.json `ai` block via /api/settings):
        temperature: 0.8,
        // Global sampler defaults (null = provider/engine default).
        // Persisted to backend config ai block as snake_case on save.
        topP: null,
        maxOutputTokens: null,
        frequencyPenalty: null,
        presencePenalty: null,
        maxContextTokens: 4096,
        ttsEnabled: true,
        ragEnabled: true,
        idleSimEnabled: false,
        idleSimIntervalSeconds: 600,
        // Character enrichment prompts (consumed by Characters page):
        charGenDescriptionPrompt: 'You are an expert character creator. Expand the provided character details into a rich, detailed background description. Return ONLY the text for the description, no markdown or extra chat.',
        charGenPersonalityPrompt: 'You are an expert character creator. Expand the provided character details into a detailed personality profile covering traits, quirks, and mannerisms. Return ONLY the text, no markdown.',
        charGenScenarioPrompt: 'You are an expert character creator. Create an engaging scenario/setting for this character based on their details. Return ONLY the text, no markdown.',
        charGenFirstMesPrompt: 'You are an expert character creator. Write an engaging first message/greeting from this character in their unique voice. Return ONLY the text, no markdown.',
        charGenMesExamplePrompt: 'You are an expert character creator. Write a few short dialogue examples showing how this character speaks. Use <START> to separate examples. Return ONLY the text, no markdown.',
        charGenSystemPromptPrompt: 'You are an expert character creator. Write a custom system prompt that instructs an AI how to play this character. Return ONLY the text, no markdown.',
        charGenVisualTagsPrompt: 'You are an expert character creator. Generate a comma-separated list of Danbooru-style visual tags that describe this character\'s appearance. Return ONLY the tags, no markdown.',
        charGenEnrichPrompt: 'You are an expert character creator. Read the provided character details and fill in ALL missing fields to enrich the character profile. Output MUST be valid JSON matching exactly these keys: "description", "personality", "scenario", "first_mes", "mes_example", "default_time", "default_location". Do not include markdown code blocks, just raw JSON.',
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
             * Update every key of one category in a single `set`, so a patch
             * read from the server re-renders `useSettings()` consumers once
             * instead of once per key.
             *
             * @param {string} category - Top-level settings group.
             * @param {object} patch    - Partial settings for that category.
             *
             * @example
             * updateCategory('ai', { temperature: 0.4, maxContextTokens: 8192 });
             */
            updateCategory: (category, patch) => {
                set((state) => {
                    if (!state.settings[category]) return state;
                    return {
                        settings: {
                            ...state.settings,
                            [category]: { ...state.settings[category], ...patch },
                        },
                    };
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
            version: 1,
            merge: (persistedState, currentState) => {
                const persistedSettings = persistedState?.settings || {};
                const settings = { ...currentState.settings };
                for (const [category, defaults] of Object.entries(currentState.settings)) {
                    const persistedCategory = persistedSettings[category];
                    if (persistedCategory && typeof persistedCategory === 'object' && !Array.isArray(persistedCategory)) {
                        settings[category] = { ...defaults, ...persistedCategory };
                    }
                }
                return { ...currentState, settings };
            }
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
 * @returns {{ updateSetting, updateSettings, updateCategory, resetSettings, resetCategory }}
 */
export const useUpdateSettings = () => {
    const updateSetting = useSettingsStore((state) => state.updateSetting);
    const updateSettings = useSettingsStore((state) => state.updateSettings);
    const updateCategory = useSettingsStore((state) => state.updateCategory);
    const resetSettings = useSettingsStore((state) => state.resetSettings);
    const resetCategory = useSettingsStore((state) => state.resetCategory);

    return {
        updateSetting,
        updateSettings,
        updateCategory,
        resetSettings,
        resetCategory
    };
};
