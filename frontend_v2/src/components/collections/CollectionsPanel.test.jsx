import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const collectionsQuery = vi.hoisted(() => ({ value: {} }));

vi.mock('../../hooks/useCollections', () => ({
    useCollections: () => collectionsQuery.value,
    useCreateCollection: () => ({ mutate: vi.fn(), isPending: false }),
    useDeleteCollection: () => ({ mutate: vi.fn(), isPending: false }),
    useRenameCollection: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock('../../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: vi.fn().mockResolvedValue(true) }),
}));

vi.mock('../CreateCollectionModal', () => ({ default: () => null }));

import CollectionsPanel from './CollectionsPanel';

/**
 * A failed collections fetch rendered as "Collection is empty".
 *
 * `useCollections()` destructured only `data`, whose `{}` default produces an
 * empty `collectionList`, so a 503 reached the same branch as a first run and
 * rendered a create button for a vault that already held collections. Found by
 * the widened `queryErrorInvariants` scan (2026-10-04).
 *
 * Also pins the button label, which read **"Add Images"** — the `collection`
 * type's default — while the handler opens the **New Collection** modal. See
 * `EmptyState.jsx`, where `primaryLabel: primaryLabel || "Add Images"` is the
 * default that these two call sites were inheriting.
 */

const existing = { 'col-1': { id: 'col-1', name: 'Portraits', imageCount: 2 } };

function renderPanel() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter>
                <CollectionsPanel isOpen onClose={vi.fn()} />
            </MemoryRouter>
        </QueryClientProvider>
    );
}

describe('CollectionsPanel', () => {
    beforeEach(() => {
        collectionsQuery.value = { data: existing, isError: false, error: null, refetch: vi.fn() };
    });

    it('states a failed fetch instead of claiming the vault is empty', () => {
        collectionsQuery.value = {
            data: {}, isError: true,
            error: new Error('503 Service Unavailable'), refetch: vi.fn(),
        };
        renderPanel();

        const alert = screen.getByRole('alert');
        expect(alert).toHaveTextContent(/could not load your collections/i);
        expect(alert).toHaveTextContent(/503 Service Unavailable/);
        expect(screen.queryByText('Collection is empty')).toBeNull();
    });

    it('offers a retry wired to the collections refetch', () => {
        const refetch = vi.fn();
        collectionsQuery.value = { data: {}, isError: true, error: new Error('boom'), refetch };
        renderPanel();

        fireEvent.click(screen.getByRole('button', { name: /try again/i }));
        expect(refetch).toHaveBeenCalledTimes(1);
    });

    it('its empty-state button says New Collection, not Add Images', () => {
        collectionsQuery.value = { data: {}, isError: false, error: null, refetch: vi.fn() };
        renderPanel();

        // The handler opens the New Collection modal, so "Add Images" is a
        // button that lies about what it does. Two buttons match the correct
        // label (the panel header's and the empty state's) — the point is that
        // neither of them reads "Add Images".
        expect(screen.queryByRole('button', { name: /add images/i })).toBeNull();
        expect(screen.getAllByRole('button', { name: /new collection/i }).length).toBeGreaterThan(0);
    });

    it('lists existing collections and no empty state at all', () => {
        renderPanel();

        expect(screen.getByText('Portraits')).toBeTruthy();
        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.queryByText('Collection is empty')).toBeNull();
    });
});