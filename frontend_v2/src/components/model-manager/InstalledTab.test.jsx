import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';

const listState = vi.hoisted(() => ({
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
            isError: false,
            error: null,
            refetch: vi.fn(),
        }),
    };
});

vi.mock('../../hooks/useProvidersPageData', () => ({
    default: () => ({ providers: [], providersLoading: false })
}));

import InstalledTab from './InstalledTab';

describe('InstalledTab image rendering', () => {
    it('renders installed model with preview image and image count badge without ReferenceError', () => {
        listState.pages = {
            pages: [{
                directory: 'checkpoints',
                files: [{
                    name: 'alpha.safetensors',
                    display_name: 'Alpha Checkpoint',
                    model_id: 'm1',
                    size: 1024 * 1024 * 500,
                    preview_url: 'https://example.com/alpha.jpg',
                    images: ['https://example.com/alpha.jpg', 'https://example.com/alpha2.jpg', 'https://example.com/alpha3.jpg'],
                    provider_statuses: { modal: { status: 'installed' } },
                    description: '',
                }]
            }]
        };

        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        render(
            <QueryClientProvider client={queryClient}>
                <InstalledTab />
            </QueryClientProvider>
        );

        expect(screen.getByText('Alpha Checkpoint')).toBeInTheDocument();
        // Image count badge shows 3
        expect(screen.getByText('3')).toBeInTheDocument();
    });
});
