import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import promptsApi from '../api/promptsApi';

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
        queryFn: async () => {
            await migrateIfNeeded();
            const { prompts } = await promptsApi.listPrompts({ limit: 500, ...filters });
            return prompts || [];
        },
        staleTime: 1 * 60 * 1000, // 1 minute
    });
}

export function usePromptCategories() {
    return useQuery({
        queryKey: ['prompts', 'categories'],
        queryFn: async () => {
            const { categories } = await promptsApi.getCategories();
            // Default categories in case backend returns empty or incomplete
            const defaults = ['All', 'Portrait', 'Landscape', 'Anime', 'Abstract', 'Realistic', 'Custom'];
            const merged = new Set([...defaults, ...(categories || [])]);
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
