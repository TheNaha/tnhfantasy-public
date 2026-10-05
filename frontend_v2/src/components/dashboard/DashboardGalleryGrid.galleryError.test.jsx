import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';

import DashboardGalleryGrid from './DashboardGalleryGrid';

/**
 * A failed gallery fetch rendered as "No images yet".
 *
 * Reproduced live at http://localhost:5174 by intercepting the facet GET and
 * answering 503: `FAILED-FETCH: no-images-yet= true | CTA= true`, next to a
 * facet panel printing "Matching total **unavailable**" from the same query.
 * The page contradicted itself and told the user their library was empty.
 *
 * The cause is structural, not a missing conditional: the grid receives a flat
 * array, and a rejected query leaves that array at length 0. Every `=== 0`
 * check downstream is satisfied by an outage, so the empty state is reached by
 * exactly the wrong path. The grid has to be told.
 *
 * Assertions here are synchronous on purpose — the known load flake in
 * `AssetTagEditor.test.jsx` is a `findBy*` under parallel load, and this file
 * must not add another one.
 */

function renderGrid(overrides = {}) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const props = {
        isLoading: false,
        isError: false,
        error: null,
        onRetry: undefined,
        viewMode: 'grid',
        displayedItems: [],
        showFavorites: false,
        activeCollection: null,
        filters: {},
        onClearFilters: vi.fn(),
        allItems: [],
        onImageClick: vi.fn(),
        onJobClick: vi.fn(),
        selectionMode: false,
        selectedFiles: new Set(),
        onToggleSelection: vi.fn(),
        isFavorite: () => false,
        onToggleFavorite: vi.fn(),
        sortedGroupedEntries: [],
        formatDateLabel: (k) => k,
        gridCols: 4,
        onDelete: vi.fn(),
        onJobDelete: vi.fn(),
        sentinelRef: { current: null },
        isFetchingNextPage: false,
        isRefreshing: false,
        ...overrides,
    };

    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter>
                <DashboardGalleryGrid {...props} />
            </MemoryRouter>
        </QueryClientProvider>
    );
}

describe('a failed gallery fetch is a failure, not an empty library', () => {
    afterEach(cleanup);

    it('states the failure and never says the library is empty', () => {
        renderGrid({ isError: true, error: new Error('503 Service Unavailable'), onRetry: vi.fn() });

        const alert = screen.getByRole('alert');
        expect(alert).toHaveTextContent(/could not load your images/i);
        expect(alert).toHaveTextContent(/503 Service Unavailable/);
        // The exact inversion this component exists to prevent.
        expect(screen.queryByText('No images yet')).toBeNull();
        expect(screen.queryByText('Start creating amazing AI-generated images with your prompts')).toBeNull();
    });

    it('offers a retry wired to the query refetch', () => {
        const onRetry = vi.fn();
        renderGrid({ isError: true, error: new Error('boom'), onRetry });

        screen.getByRole('button', { name: /try again/i }).click();
        expect(onRetry).toHaveBeenCalledTimes(1);
    });

    it('still renders the real empty state when the fetch genuinely succeeded', () => {
        renderGrid({ isError: false, displayedItems: [] });

        expect(screen.getByText('No images yet')).toBeTruthy();
        expect(screen.queryByRole('alert')).toBeNull();
    });

    it('an error while items are already on screen does not blank the grid', () => {
        // A background page failing is not a reason to destroy the first page
        // the user is reading. Only a query that has never produced a page is a
        // total failure, and `displayedItems.length === 0` is what says so.
        renderGrid({
            isError: true,
            error: new Error('boom'),
            onRetry: vi.fn(),
            displayedItems: [{ type: 'image', name: 'a.png', date: '2026-10-04', mtime: '2026-10-04T00:00:00Z' }],
            sortedGroupedEntries: [['2026-10-04', [{ type: 'image', name: 'a.png', date: '2026-10-04', mtime: '2026-10-04T00:00:00Z' }]]],
        });

        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.queryByText('No images yet')).toBeNull();
    });
});

describe('the collection empty state button says what it does', () => {
    afterEach(cleanup);

    it('does not offer "Add Images" for a button that exits the collection', () => {
        renderGrid({ activeCollection: 'col-1', filters: {}, onClearFilters: vi.fn() });

        // The `collection` type defaults to "Add Images", which opens the New
        // Collection modal in CollectionsPanel and does nothing here — while
        // `onAction` here leaves the collection entirely.
        expect(screen.queryByRole('button', { name: /add images/i })).toBeNull();
        expect(screen.getByRole('button', { name: /back to all images/i })).toBeTruthy();
    });
});
