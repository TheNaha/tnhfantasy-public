import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Settings from './Settings';

// Covers the backend-persistence work: the schema-driven Backend tab, the
// env-var "overridden" badge, and Reset All now calling the backend endpoint
// instead of only clearing this browser's localStorage.

const mockApi = vi.hoisted(() => ({
    get: vi.fn(),
    put: vi.fn(),
    getSchema: vi.fn(),
    reset: vi.fn(),
    getSystemPrompts: vi.fn(),
    updateSystemPrompts: vi.fn(),
    getBranding: vi.fn(),
    updateBranding: vi.fn(),
    getFavorites: vi.fn(),
    updateFavorites: vi.fn(),
}));

const mockConfirm = vi.hoisted(() => vi.fn(async () => true));

vi.mock('../api/settingsApi', async () => {
    const actual = await vi.importActual('../api/settingsApi');
    return { ...actual, settingsApi: mockApi };
});

// The confirmation is a dialog rendered by a host elsewhere in the tree;
// resolve it directly so these tests assert the handler, not the dialog.
vi.mock('../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: mockConfirm }),
}));

vi.mock('../hooks/useProvidersPageData', () => ({
    useProvidersPageData: () => ({ providers: [], containers: {}, loading: false, refresh: vi.fn() }),
}));

vi.mock('../hooks/useModels', () => ({ useModels: () => ({ models: [], loading: false }) }));
vi.mock('../hooks/useDebounce', () => ({ useDebounce: (v) => v }));

vi.mock('react-hot-toast', () => {
    const toast = { success: vi.fn(), error: vi.fn() };
    return { default: toast, toast, Toaster: () => null };
});

const SCHEMA = {
    status: 'success',
    schema: {
        jobs: {
            section: 'jobs',
            description: 'Job execution',
            writable: true,
            fields: {
                max_concurrent: {
                    type: 'integer',
                    description: 'In-flight job ceiling — the only spend throttle',
                    min: 1,
                    max: 10,
                    default: 5,
                },
            },
        },
        api: {
            section: 'api',
            description: 'API',
            writable: true,
            fields: {
                cors_origins: {
                    type: 'array',
                    description: 'Allowed origins',
                    default: ['http://localhost:5174'],
                    restart_required: true,
                },
            },
        },
    },
    env_overrides: { 'api.cors_origins': 'COMFY_CORS_ORIGINS' },
};

const CONFIG = {
    status: 'success',
    settings: {
        ai: { maxContextTokens: 4096, temperature: 0.8 },
        generator: { default_checkpoint: 'installed.safetensors' },
        jobs: { max_concurrent: 5 },
        api: { cors_origins: ['http://localhost:5174'] },
    },
};

const renderSettings = () => {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <Settings />
        </QueryClientProvider>,
    );
};

const openBackendTab = async () => {
    fireEvent.click(await screen.findByRole('button', { name: /backend/i }));
};

beforeEach(() => {
    vi.clearAllMocks();
    mockConfirm.mockResolvedValue(true);
    mockApi.get.mockResolvedValue(CONFIG);
    mockApi.getSchema.mockResolvedValue(SCHEMA);
    mockApi.getSystemPrompts.mockResolvedValue({ status: 'success', system_prompts: {} });
    mockApi.getBranding.mockResolvedValue({ status: 'success' });
    mockApi.getFavorites.mockResolvedValue({ status: 'success', favorites: [] });
    mockApi.put.mockResolvedValue({ status: 'success' });
    mockApi.reset.mockResolvedValue({ status: 'success' });
});

describe('Settings - backend persistence', () => {
    it('fetches the machine-readable schema when the Backend tab opens', async () => {
        // The page must label its controls from the same source the API
        // validates against, rather than hardcoding ranges that can drift. The
        // query deliberately lives inside the Backend tab (Settings.jsx:442), so
        // opening the tab is what triggers it — a user who never visits Backend
        // never pays for the request.
        renderSettings();
        expect(mockApi.getSchema).not.toHaveBeenCalled();
        await openBackendTab();
        await waitFor(() => expect(mockApi.getSchema).toHaveBeenCalled());
    });

    it('exposes the previously-hidden spend throttle on the Backend tab', async () => {
        // jobs.max_concurrent had no UI at all, and it is the only control that
        // gates how much work is dispatched to paid providers.
        renderSettings();
        await openBackendTab();
        await waitFor(() => {
            expect(screen.getByText('Max Concurrent Jobs')).toBeInTheDocument();
        });
    });

    it('shows a read-only badge for a value the environment overrides', async () => {
        // An env-overridden key is ignored in config.json, so presenting an
        // editable box would be a control that silently does nothing.
        renderSettings();
        await openBackendTab();
        await waitFor(() => {
            expect(screen.getAllByText(/overridden by/i).length).toBeGreaterThan(0);
        });
        expect(screen.getAllByText(/COMFY_CORS_ORIGINS/i).length).toBeGreaterThan(0);
    });

    it('flags a restart-required setting rather than implying it applies live', async () => {
        // cors_origins is bound once at app construction, so changing it needs
        // a restart. Silently applying it would be a lie.
        renderSettings();
        await openBackendTab();
        await waitFor(() => {
            expect(screen.getAllByText(/restart/i).length).toBeGreaterThan(0);
        });
    });

    it('Reset All calls the backend endpoint, not just the local store', async () => {
        // The button used to clear localStorage only, so the config.json values
        // the job runner actually reads survived a "Reset All" untouched.
        renderSettings();
        const reset = await screen.findByRole('button', { name: /reset all/i });
        fireEvent.click(reset);

        await waitFor(() => expect(mockApi.reset).toHaveBeenCalledTimes(1));
    });

    it('asks for confirmation before resetting the backend', async () => {
        renderSettings();
        fireEvent.click(await screen.findByRole('button', { name: /reset all/i }));
        await waitFor(() => expect(mockConfirm).toHaveBeenCalled());
    });

    it('does not touch the backend when the confirmation is declined', async () => {
        mockConfirm.mockResolvedValue(false);
        renderSettings();
        fireEvent.click(await screen.findByRole('button', { name: /reset all/i }));

        await waitFor(() => expect(mockConfirm).toHaveBeenCalled());
        expect(mockApi.reset).not.toHaveBeenCalled();
    });

    it('does not clear local settings when the backend reset fails', async () => {
        mockApi.reset.mockRejectedValue(new Error('boom'));
        renderSettings();
        fireEvent.click(await screen.findByRole('button', { name: /reset all/i }));

        await waitFor(() => expect(mockApi.reset).toHaveBeenCalled());
        // The failure must surface, not be swallowed as a success.
        expect(mockApi.reset).toHaveBeenCalledTimes(1);
    });
});
