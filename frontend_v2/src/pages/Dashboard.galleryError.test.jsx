import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * A failed gallery fetch rendered as "No images yet".
 *
 * Reproduced live at http://localhost:5174 by intercepting the facet GET and
 * answering 503: the page printed "No images yet / Start creating amazing
 * AI-generated images…" with a working Generate CTA while the facet panel, 40
 * lines up and reading the same query, printed "Matching total unavailable".
 * The UI contradicted itself and told the user their library was empty.
 *
 * `DashboardGalleryGrid.galleryError.test.jsx` covers the grid's own decision.
 * This covers the half that made the audit's finding possible in the first
 * place: `Dashboard` destructured `{data, …, refetch}` and never `isError`, so
 * there was nothing to hand the grid even if the grid had asked. A grid-level
 * fix alone passes that suite against an unchanged page.
 *
 * The sessions query in this same file has been error-gated the whole time —
 * that is the model, and its presence is what makes the omission look like an
 * accident rather than a decision.
 */

const galleryQuery = vi.hoisted(() => ({
    value: {
        data: { pages: [] },
        error: null,
        fetchNextPage: vi.fn(),
        hasNextPage: false,
        isError: false,
        isFetching: false,
        isFetchingNextPage: false,
        isLoading: false,
        refetch: vi.fn(),
    },
}));

vi.mock('../hooks/useGallery', async (importOriginal) => ({
    ...(await importOriginal()),
    useGallery: () => galleryQuery.value,
}));

vi.mock('../hooks/useActiveJobs', () => ({ useActiveJobs: () => ({ data: [] }) }));
vi.mock('../hooks/useCollections', () => ({
    useCollections: () => ({ data: {} }),
    useCollectionImages: () => ({ data: [] }),
    useAddImagesToCollection: () => ({ mutateAsync: vi.fn() }),
    useRemoveImagesFromCollection: () => ({ mutate: vi.fn() }),
    useMoveImagesBetweenCollections: () => ({ mutateAsync: vi.fn() }),
}));
vi.mock('../hooks/useSessions', () => ({
    useSessions: () => ({ data: undefined, isLoading: false, isError: false, hasNextPage: false, fetchNextPage: vi.fn(), isFetchingNextPage: false }),
    flattenSessionPages: () => [],
}));
vi.mock('../hooks/useFavorites', () => ({
    useFavorites: () => ({ favorites: [], isFavorite: () => false, toggleFavorite: vi.fn(), addFavorites: vi.fn() }),
}));
vi.mock('../hooks/useDashboardItems', () => ({
    useDashboardItems: () => ({
        allItems: [], displayedItems: [], selectedJob: null,
        sortedGroupedEntries: [], formatDateLabel: (k) => k,
    }),
}));
vi.mock('../hooks/useInfiniteScroll', () => ({ useInfiniteScroll: () => ({ current: null }) }));
vi.mock('../hooks/usePullToRefresh', () => ({
    usePullToRefresh: () => ({ isRefreshing: false, pullDistance: 0, isPulling: false }),
    PullToRefreshIndicator: () => null,
}));

// The chrome around the grid is not what this test is about, and each of these
// pulls its own query/websocket surface into the tree.
vi.mock('../components/QueueVisualization', () => ({ default: () => null }));
vi.mock('../components/dashboard/FailedJobsPanel', () => ({ default: () => null }));
vi.mock('../components/dashboard/DashboardHeaderToolbar', () => ({ default: () => null }));
vi.mock('../components/dashboard/GalleryDateRail', () => ({ default: () => null }));
vi.mock('../components/dashboard/DashboardOverlays', () => ({ default: () => null }));
vi.mock('../components/dashboard/SessionPanel', () => ({
    default: () => null,
    SessionViewPlaceholder: () => null,
}));

import Dashboard from './Dashboard';

function renderDashboard() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter><Dashboard /></MemoryRouter>
        </QueryClientProvider>
    );
}

describe('the dashboard grid is told when the gallery query failed', () => {
    beforeEach(() => {
        galleryQuery.value = {
            data: { pages: [] },
            error: null,
            fetchNextPage: vi.fn(),
            hasNextPage: false,
            isError: false,
            isFetching: false,
            isFetchingNextPage: false,
            isLoading: false,
            refetch: vi.fn(),
        };
    });

    it('renders the failure instead of "No images yet" when the fetch 503s', () => {
        galleryQuery.value.isError = true;
        galleryQuery.value.error = new Error('503 Service Unavailable');
        galleryQuery.value.refetch = vi.fn();

        renderDashboard();

        expect(screen.getByRole('alert')).toHaveTextContent(/could not load your images/i);
        expect(screen.queryByText('No images yet')).toBeNull();
    });

    it('wires the retry button to the gallery refetch', () => {
        galleryQuery.value.isError = true;
        galleryQuery.value.error = new Error('boom');
        const refetch = vi.fn();
        galleryQuery.value.refetch = refetch;

        renderDashboard();
        screen.getByRole('button', { name: /try again/i }).click();

        expect(refetch).toHaveBeenCalledTimes(1);
    });

    it('still says "No images yet" when the fetch succeeded and returned nothing', () => {
        renderDashboard();

        expect(screen.getByText('No images yet')).toBeTruthy();
        expect(screen.queryByRole('alert')).toBeNull();
    });
});
