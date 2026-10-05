import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import promptsApi from '../api/promptsApi';
import { DEFAULT_PROMPT_CATEGORIES } from '../constants/prompts';

const MIGRATION_KEY = 'prompt-library-migrated';
const OLD_STORAGE_KEY = 'prompt-library-storage';

async function migrateIfNeeded() {
    const migrated = localStorage.getItem(MIGRATION_KEY);
    if (migrated !== 'true') {
        const oldData = localStorage.getItem(OLD_STORAGE_KEY);
        if (oldData) {
            try {
                const parsed = JSON.parse(oldData);
                if (parsed.state?.prompts?.length > 0) {

                    // Format for API
                    const promptsToMigrate = parsed.state.prompts.map(p => ({
                        name: p.name || 'Untitled',
                        text: p.text || '',
                        negative: p.negative || null,
                        category: p.category || 'Custom',
                        description: p.description || null,
                        tags: p.tags || [],
                        favorite: p.favorite || false,
                        settings: null
                    }));

                    await promptsApi.importPrompts(promptsToMigrate);
                }
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
}

export function usePrompts(filters = {}) {
    return useQuery({
        queryKey: ['prompts', filters],
        queryFn: async ({ signal }) => {
            await migrateIfNeeded();
            const { prompts } = await promptsApi.listPrompts({ limit: 500, ...filters }, { signal });
            return prompts || [];
        },
        staleTime: 1 * 60 * 1000, // 1 minute
    });
}

export function usePromptCategories() {
    return useQuery({
        queryKey: ['prompts', 'categories'],
        // Not `initialData`: that would be written to the cache as if it had
        // been fetched, and the first real request would then be skipped until
        // the stale time expired. The filter row needs *a* list on the first
        // render, not a fake fetch.
        placeholderData: DEFAULT_PROMPT_CATEGORIES,
        queryFn: async ({ signal }) => {
            const { categories } = await promptsApi.getCategories({ signal });
            // Never empty: the filter row renders straight off this, and an
            // empty array means no categories until the request settles.
            const merged = new Set([...DEFAULT_PROMPT_CATEGORIES, ...(categories || [])]);
            return Array.from(merged);
        },
        staleTime: 5 * 60 * 1000,
    });
}

export function useCreatePrompt() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (promptData) => {
            return promptsApi.createPrompt(promptData);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['prompts'] });
        }
    });
}

export function useUpdatePrompt() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ id, updates, ...inlineUpdates }) => {
            return promptsApi.updatePrompt(id, updates ?? inlineUpdates);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['prompts'] });
        }
    });
}

export function useDeletePrompt() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id) => {
            return promptsApi.deletePrompt(id);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['prompts'] });
        }
    });
}

export function useImportPrompts() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (payload) => {
            const imported = typeof payload === 'string' ? JSON.parse(payload) : payload;
            if (!Array.isArray(imported)) {
                throw new Error('Invalid format: expected array');
            }
            const result = await promptsApi.importPrompts(imported);
            return { success: true, count: result.imported };
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['prompts'] });
        }
    });
}

export function useIncrementPromptUsage() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (id) => {
            return promptsApi.incrementUsage(id);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['prompts'] });
        }
    });
}
