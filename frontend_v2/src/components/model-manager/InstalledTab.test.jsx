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
vi.mock('../../api', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        modelsApi: {
            ...actual.modelsApi,
            getStorageBreakdown: vi.fn().mockResolvedValue({
                total_bytes: 150000000000,
                total_models: 650,
                total_files: 700,
                categories: [
                    {
                        directory: 'checkpoints',
                        total_bytes: 100000000000,
                        total_models: 15,
                        total_files: 19,
                        percentage: 66.7,
                    },
                    {
                        directory: 'loras',
                        total_bytes: 50000000000,
                        total_models: 635,
                        total_files: 681,
                        percentage: 33.3,
                    },
                ],
            }),
        },
    };
});


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

    it('renders storage breakdown button and toggles breakdown grid', async () => {
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        render(
            <QueryClientProvider client={queryClient}>
                <InstalledTab />
            </QueryClientProvider>
        );

        expect(screen.getByText('Library Storage')).toBeInTheDocument();
        const breakdownBtn = await screen.findByRole('button', { name: /breakdown/i });
        expect(breakdownBtn).toBeInTheDocument();
        breakdownBtn.click();
        expect(await screen.findByText('66.7%')).toBeInTheDocument();
        expect(await screen.findByText('33.3%')).toBeInTheDocument();
        expect(screen.getAllByText('LoRAs').length).toBeGreaterThanOrEqual(2);
    });
});
