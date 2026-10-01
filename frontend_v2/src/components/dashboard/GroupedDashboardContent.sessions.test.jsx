import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    listSessions: vi.fn(),
    listSessionAssets: vi.fn(),
    createSession: vi.fn(),
    updateSession: vi.fn(),
    deleteSession: vi.fn(),
    addSessionAssets: vi.fn(),
    removeSessionAsset: vi.fn(),
    splitSession: vi.fn(),
    mergeSession: vi.fn(),
    detectSessions: vi.fn(),
    getSession: vi.fn(),
}));

vi.mock('../../api/sessionsApi', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, ...apiMock };
});

import GroupedDashboardContent from './GroupedDashboardContent';
import { buildSessionGroupedEntries } from '../../utils/dashboardItems';

function makeSession(overrides = {}) {
    return {
        id: 's1',
        name: 'Autumn portraits',
        description: null,
        signature: null,
        auto_detected: true,
        locked: false,
        workspace: 'main',
        start_at: '2026-09-27T14:00:00Z',
        end_at: '2026-09-27T14:40:00Z',
        image_count: 2,
        thumbnail: null,
        created_at: '2026-09-27T14:00:00Z',
        updated_at: '2026-09-27T14:40:00Z',
        deleted_at: null,
        ...overrides,
    };
}

function renderContent(entries, viewMode = 'session') {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
        <QueryClientProvider client={queryClient}>
            <GroupedDashboardContent
                viewMode={viewMode}
                sortedGroupedEntries={entries}
                formatDateLabel={(key) => `Date: ${key}`}
                gridCols={4}
                selectedFiles={new Set()}
                selectionMode={false}
                handleJobClick={vi.fn()}
                handleImageClick={vi.fn()}
                toggleSelection={vi.fn()}
                isFavorite={() => false}
                handleToggleFavorite={vi.fn()}
                handleDelete={vi.fn()}
                handleJobDelete={vi.fn()}
            />
        </QueryClientProvider>,
    );
}

describe('GroupedDashboardContent in session view mode', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('renders one unit per session, not a date heading', async () => {
        const entries = buildSessionGroupedEntries([
            makeSession({ id: 'a', name: 'Autumn portraits', image_count: 4 }),
            makeSession({ id: 'b', name: 'Winter set', image_count: 9 }),
        ]);

        renderContent(entries);

        expect(await screen.findByText('Autumn portraits')).toBeInTheDocument();
        expect(screen.getByText('Winter set')).toBeInTheDocument();
        expect(screen.getByText('4 images')).toBeInTheDocument();
        expect(screen.getByText('9 images')).toBeInTheDocument();
        expect(screen.queryByText(/^Date: /)).not.toBeInTheDocument();
    });

    it('shows the auto-detected badge on a detected session and Curated on a hand-made one', async () => {
        const entries = buildSessionGroupedEntries([
            makeSession({ id: 'a', name: 'Detected run', auto_detected: true, locked: false }),
            makeSession({ id: 'b', name: 'Hand made', auto_detected: false, locked: true }),
        ]);

        renderContent(entries);

        const detected = await screen.findByText('Detected run');
        const detectedCard = detected.closest('section');
        expect(detectedCard).toHaveTextContent('Auto-detected');
        expect(detectedCard).not.toHaveTextContent('Curated');
        expect(detectedCard).not.toHaveTextContent('Locked');

        const curated = screen.getByText('Hand made').closest('section');
        expect(curated).toHaveTextContent('Curated');
        expect(curated).toHaveTextContent('Locked');
    });

    it('falls back to "Untitled session" when an auto-detected row has no name', async () => {
        renderContent(buildSessionGroupedEntries([makeSession({ name: null })]));
        expect(await screen.findByText('Untitled session')).toBeInTheDocument();
    });

    /* This used to assert `listSessionAssets` was NOT called until a session was
       expanded, which was correct when the collapsed card showed a single 56px
       thumbnail. It does not hold now: the card renders a two-row filmstrip of
       the session's images, which cannot be built from `item.thumbnail` alone, so
       the members are fetched for collapsed sessions too.

       The cost is bounded on purpose. The virtualizer keeps roughly a dozen rows
       mounted, so this is a dozen small cached requests (`staleTime` 5 minutes)
       rather than one per session in a 1,400-session library — and it is the
       difference between a media-oriented view and one that shows a thumbnail
       and hides everything else behind a click. */
    it('fetches members for a collapsed session so the filmstrip has images', async () => {
        apiMock.listSessionAssets.mockResolvedValue({
            session_id: 's1',
            assets: [
                { id: 'a1', relative_path: 'main/a1.png' },
                { id: 'a2', relative_path: 'main/a2.png' },
            ],
            total: 2,
            limit: 200,
            offset: 0,
        });

        renderContent(buildSessionGroupedEntries([makeSession()]));
        await screen.findByText('Autumn portraits');
        await waitFor(() => expect(apiMock.listSessionAssets).toHaveBeenCalled());

        // And the tiles reach the DOM, which is the point of fetching them.
        expect(document.querySelectorAll('img[src*="a1.png"], img[src*="a2.png"]').length)
            .toBeGreaterThan(0);
    });

    it('reports a members failure inside the expanded card', async () => {
        apiMock.listSessionAssets.mockRejectedValue(new Error('Session not found'));

        renderContent(buildSessionGroupedEntries([makeSession()]));
        await screen.findByText('Autumn portraits');
        fireEvent.click(screen.getByRole('button', { expanded: false }));

        await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Session not found'));
    });

    it('keeps rendering date headings in the other view modes', () => {
        const entries = [['2026-09-27', [{ type: 'image', name: 'a.png' }]]];
        renderContent(entries, 'grid');
        expect(screen.getByText('Date: 2026-09-27')).toBeInTheDocument();
    });
});
