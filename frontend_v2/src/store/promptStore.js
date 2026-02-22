import { create } from 'zustand';
import * as promptsApi from '../api/promptsApi';

/**
 * Prompt Library Store
 * Server-side storage with FTS5 search
 * Migrates from localStorage on first load
 */

const MIGRATION_KEY = 'prompt-library-migrated';
const OLD_STORAGE_KEY = 'prompt-library-storage';

export const usePromptStore = create((set, get) => ({
    // State
    prompts: [],
    categories: ['All', 'Portrait', 'Landscape', 'Anime', 'Abstract', 'Realistic', 'Custom'],
    isLoading: false,
    error: null,
    initialized: false,

    // Initialize - fetch from server and migrate if needed
    initialize: async () => {
        if (get().initialized) return;

        set({ isLoading: true, error: null });

        try {
            // Check for localStorage data to migrate
            const migrated = localStorage.getItem(MIGRATION_KEY);
            if (!migrated) {
                const oldData = localStorage.getItem(OLD_STORAGE_KEY);
                if (oldData) {
                    try {
                        const parsed = JSON.parse(oldData);
                        if (parsed.state?.prompts?.length > 0) {
                            console.log('[PromptStore] Migrating', parsed.state.prompts.length, 'prompts from localStorage');

                            // Format for API
                            const promptsToMigrate = parsed.state.prompts.map(p => ({
                                name: p.name || 'Untitled',
                                text: p.text || '',
                                negative: p.negative || null,
                                category: p.category || 'Custom',
                                description: p.description || null,
                                tags: p.tags || [],
                                favorite: p.favorite || false,
                                settings: null // Old format didn't have full settings
                            }));

                            await promptsApi.importPrompts(promptsToMigrate);
                            console.log('[PromptStore] Migration complete');
                        }

                        // Mark as migrated and clean up
                        localStorage.setItem(MIGRATION_KEY, 'true');
                        localStorage.removeItem(OLD_STORAGE_KEY);
                    } catch (e) {
                        console.warn('[PromptStore] Migration failed:', e);
                        localStorage.setItem(MIGRATION_KEY, 'failed');
                    }
                } else {
                    localStorage.setItem(MIGRATION_KEY, 'true');
                }
            }

            // Fetch from server
            const { prompts } = await promptsApi.listPrompts({ limit: 500 });
            const { categories } = await promptsApi.getCategories();

            set({
                prompts,
                categories,
                isLoading: false,
                initialized: true
            });
        } catch (error) {
            console.error('[PromptStore] Failed to initialize:', error);
            set({ error: error.message, isLoading: false, initialized: true });
        }
    },

    // Refresh prompts from server
    refresh: async () => {
        set({ isLoading: true });
        try {
            const { prompts } = await promptsApi.listPrompts({ limit: 500 });
            set({ prompts, isLoading: false });
        } catch (error) {
            set({ error: error.message, isLoading: false });
        }
    },

    // Add a new prompt
    addPrompt: async (promptData) => {
        try {
            const newPrompt = await promptsApi.createPrompt(promptData);
            set((state) => ({
                prompts: [newPrompt, ...state.prompts]
            }));
            return newPrompt;
        } catch (error) {
            console.error('Failed to create prompt:', error);
            throw error;
        }
    },

    // Update existing prompt
    updatePrompt: async (id, updates) => {
        try {
            const updatedPrompt = await promptsApi.updatePrompt(id, updates);
            set((state) => ({
                prompts: state.prompts.map(p =>
                    p.id === id ? updatedPrompt : p
                )
            }));
            return updatedPrompt;
        } catch (error) {
            console.error('Failed to update prompt:', error);
            throw error;
        }
    },

    // Delete prompt
    deletePrompt: async (id) => {
        try {
            await promptsApi.deletePrompt(id);
            set((state) => ({
                prompts: state.prompts.filter(p => p.id !== id)
            }));
        } catch (error) {
            console.error('Failed to delete prompt:', error);
            throw error;
        }
    },

    // Toggle favorite
    toggleFavorite: async (id) => {
        const prompt = get().prompts.find(p => p.id === id);
        if (!prompt) return;

        try {
            const updated = await promptsApi.updatePrompt(id, { favorite: !prompt.favorite });
            set((state) => ({
                prompts: state.prompts.map(p =>
                    p.id === id ? updated : p
                )
            }));
        } catch (error) {
            console.error('Failed to toggle favorite:', error);
        }
    },

    // Increment usage count
    incrementUsage: async (id) => {
        try {
            await promptsApi.incrementUsage(id);
            set((state) => ({
                prompts: state.prompts.map(p =>
                    p.id === id ? { ...p, usage_count: (p.usage_count || 0) + 1 } : p
                )
            }));
        } catch (error) {
            console.error('Failed to increment usage:', error);
        }
    },

    // Search prompts (server-side FTS5)
    searchPrompts: async (query) => {
        if (!query?.trim()) return get().prompts;

        try {
            const { prompts } = await promptsApi.listPrompts({ q: query });
            return prompts;
        } catch (error) {
            console.error('Search failed:', error);
            // Fall back to local search
            const lowerQuery = query.toLowerCase();
            return get().prompts.filter(p =>
                p.name?.toLowerCase().includes(lowerQuery) ||
                p.text?.toLowerCase().includes(lowerQuery) ||
                p.description?.toLowerCase().includes(lowerQuery)
            );
        }
    },

    // Filter by category (local)
    filterByCategory: (category) => {
        const { prompts } = get();
        if (category === 'All') return prompts;
        return prompts.filter(p => p.category === category);
    },

    // Get favorites (local)
    getFavorites: () => {
        return get().prompts.filter(p => p.favorite);
    },

    // Get most used (local)
    getMostUsed: (limit = 10) => {
        return [...get().prompts]
            .sort((a, b) => (b.usage_count || 0) - (a.usage_count || 0))
            .slice(0, limit);
    },

    // Export prompts as JSON
    exportPrompts: async () => {
        const { prompts } = await promptsApi.exportPrompts();
        return JSON.stringify(prompts, null, 2);
    },

    // Import prompts from JSON
    importPrompts: async (jsonString) => {
        try {
            const imported = JSON.parse(jsonString);
            if (!Array.isArray(imported)) {
                throw new Error('Invalid format: expected array');
            }

            const result = await promptsApi.importPrompts(imported);
            await get().refresh();

            return { success: true, count: result.imported };
        } catch (error) {
            return { success: false, error: error.message };
        }
    },

    // Clear all prompts
    clearAllPrompts: async () => {
        const prompts = get().prompts;
        for (const prompt of prompts) {
            try {
                await promptsApi.deletePrompt(prompt.id);
            } catch (e) {
                console.error('Failed to delete prompt:', prompt.id);
            }
        }
        set({ prompts: [] });
    },

    // Add custom category (local only, categories are derived from prompts)
    addCategory: (categoryName) => {
        set((state) => {
            if (state.categories.includes(categoryName)) {
                return state;
            }
            return {
                categories: [...state.categories, categoryName]
            };
        });
    },
}));

export default usePromptStore;
