import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/promptsApi', () => ({
    listPrompts: vi.fn(),
    getCategories: vi.fn(),
    getFavorites: vi.fn(),
    getMostUsed: vi.fn(),
    getPrompt: vi.fn(),
    createPrompt: vi.fn(),
    updatePrompt: vi.fn(),
    deletePrompt: vi.fn(),
    incrementUsage: vi.fn(),
    importPrompts: vi.fn(),
    exportPrompts: vi.fn(),
}));

describe('usePromptStore initialization', () => {
    let usePromptStore;
    let promptsApi;

    beforeEach(async () => {
        vi.resetModules();
        promptsApi = await import('../api/promptsApi');
        const storeMod = await import('./promptStore.js');
        usePromptStore = storeMod.default;

        localStorage.clear();
        usePromptStore.setState({
            prompts: [],
            categories: ['All', 'Custom'],
            isLoading: false,
            error: null,
            initialized: false,
        });
    });

    it('initializes prompt data from the backend', async () => {
        promptsApi.listPrompts.mockResolvedValue({
            prompts: [{ id: 'prompt-1', name: 'Portrait', text: 'portrait prompt' }],
        });
        promptsApi.getCategories.mockResolvedValue({
            categories: ['All', 'Portrait', 'Custom'],
        });

        await usePromptStore.getState().initialize();

        const state = usePromptStore.getState();
        expect(state.initialized).toBe(true);
        expect(state.prompts).toHaveLength(1);
        expect(state.categories).toEqual(['All', 'Portrait', 'Custom']);
    });

    it('keeps initialized false when initialization fails so it can retry', async () => {
        promptsApi.listPrompts.mockRejectedValue(new Error('backend unavailable'));

        await usePromptStore.getState().initialize();

        const state = usePromptStore.getState();
        expect(state.initialized).toBe(false);
        expect(state.error).toBe('backend unavailable');
    });
});
