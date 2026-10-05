import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';

/**
 * `InstalledTab`'s own infinite query, and the memoised row extracted from its
 * grid. Its own file because `ModelSelector` mocks the same module.
 */
const listState = vi.hoisted(() => ({
    isError: false,
    error: null,
    refetch: vi.fn(),
    pages: { pages: [] },
}));

vi.mock('@tanstack/react-query', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        useInfiniteQuery: () => ({
            data: listState.pages,
            hasNextPage: false,
            isFetching: false,
            isFetchingNextPage: false,
            isError: listState.isError,
            error: listState.error,
            refetch: listState.refetch,
        }),
    };
});

import InstalledTab from './InstalledTab';

// The tab reaches for the query client in `useInfiniteScroll` and the settings
// store, so it needs a real provider even though the list query is mocked.
function renderTab() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
        <QueryClientProvider client={queryClient}>
            <InstalledTab />
        </QueryClientProvider>
    );
}

const ONE_MODEL = {
    name: 'alpha.safetensors',
    display_name: 'Alpha',
    model_id: 'm1',
    size: 1024,
    civitai_id: null,
    preview: null,
    provider_statuses: { modal: { status: 'installed' } },
    description: '',
};

describe('InstalledTab — a failed model fetch is not an empty install list', () => {
    it('states the failure instead of "No models found"', () => {
        listState.isError = true;
        listState.error = new Error('503 from /api/files');
        listState.pages = { pages: [] };

        renderTab();

        expect(screen.getAllByRole('alert').length).toBeGreaterThan(0);
        expect(screen.queryByText('No models found')).toBeNull();
    });

    it('offers a retry wired to the query refetch', () => {
        listState.isError = true;
        listState.refetch.mockClear();

        renderTab();

        screen.getAllByRole('button', { name: /try again/i })[0].click();
        expect(listState.refetch).toHaveBeenCalled();
    });

    it('still shows the empty copy when the fetch succeeded and returned nothing', () => {
        listState.isError = false;
        listState.pages = { pages: [] };

        renderTab();

        expect(screen.getByText('No models found')).toBeTruthy();
    });

    it('renders the installed rows when the fetch succeeded', () => {
        listState.isError = false;
        listState.pages = { pages: [{ files: [ONE_MODEL], directory: 'checkpoints' }] };

        renderTab();

        expect(screen.queryByText('No models found')).toBeNull();
        expect(screen.getByText('Alpha')).toBeTruthy();
    });
});