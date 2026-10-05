/**
 * "Reset layout" has to actually discard the saved layout.
 *
 * The button used to call `window.location.reload()`. The layout is persisted
 * server-side at `PUT /api/v2/world-vault/graph-layout/?name=…` and nothing ever
 * deleted it, so reloading re-read the saved layout and restored exactly what the
 * user was trying to discard — a button that announced success and delivered
 * the opposite. The backend route `DELETE /api/v2/world-vault/graph-layout/`
 * (`backend_v2/api/routes/world_vault/graph_layout.py:53`) had zero frontend
 * callers, so it existed and was unused.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
}));

vi.mock('../api', () => ({ api: apiMock }));

const RELATIONSHIPS = {
    character_chats: [],
    character_stories: [],
    chat_stories: [],
    lorebook_links: [],
    voice_links: [],
    location_links: [],
};

const SAVED_LAYOUT = {
    name: 'default',
    nodes: [{ entity_type: 'character', entity_id: 'c1', x: 111, y: 222 }],
};

function renderGraph() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter>
                <RelationshipGraph />
            </MemoryRouter>
        </QueryClientProvider>,
    );
}

let RelationshipGraph;

beforeEach(async () => {
    vi.clearAllMocks();
    RelationshipGraph = (await import('./RelationshipGraph')).default;
    apiMock.get.mockImplementation((url) => {
        if (String(url).includes('relationships')) return Promise.resolve(RELATIONSHIPS);
        if (String(url).includes('graph-layout')) return Promise.resolve(SAVED_LAYOUT);
        return Promise.resolve({});
    });
    apiMock.delete.mockResolvedValue({ status: 'success' });
    apiMock.put.mockResolvedValue({ status: 'success' });
});

describe('RelationshipGraph — reset layout', () => {
    it('deletes the saved layout instead of reloading the page', async () => {
        const reload = vi.fn();
        const original = window.location;
        // `window.location.reload()` cannot be spied through `vi.spyOn` on the
        // real Location object, so the assertion is on the DELETE: if the button
        // still reloaded, the delete would never be issued and the saved layout
        // would survive the click.
        delete window.location;
        window.location = { ...original, reload };
        try {
            renderGraph();
            await screen.findByTitle('Reset layout');
            await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith('/api/v2/world-vault/graph-layout/?name=default'));

            fireEvent.click(screen.getByRole('button', { name: /reset layout/i }));

            await waitFor(() => {
                expect(apiMock.delete).toHaveBeenCalledWith('/api/v2/world-vault/graph-layout/?name=default');
            });
            expect(reload).not.toHaveBeenCalled();
        } finally {
            window.location = original;
        }
    });

    it('re-reads the layout after the delete, so the graph re-lays out on this visit', async () => {
        renderGraph();
        await screen.findByTitle('Reset layout');
        await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith('/api/v2/world-vault/graph-layout/?name=default'));
        const readsBefore = apiMock.get.mock.calls.filter((c) => String(c[0]).includes('graph-layout')).length;

        apiMock.get.mockImplementation((url) => {
            if (String(url).includes('graph-layout')) return Promise.resolve(null);
            return Promise.resolve(RELATIONSHIPS);
        });
        fireEvent.click(screen.getByTitle('Reset layout'));

        await waitFor(() => {
            const readsAfter = apiMock.get.mock.calls.filter((c) => String(c[0]).includes('graph-layout')).length;
            expect(readsAfter).toBeGreaterThan(readsBefore);
        });
        expect(apiMock.put).not.toHaveBeenCalled();
    });
});
