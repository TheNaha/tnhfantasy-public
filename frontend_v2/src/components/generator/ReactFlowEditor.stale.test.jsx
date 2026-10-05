import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * `/advanced`'s node palette rendered from a days-old cache with nothing said.
 *
 * `useObjectInfo`'s `catch` returned the IndexedDB payload, and returning from a
 * `queryFn` is a SUCCESS — so `ReactFlowEditor`'s `error`, which it destructured
 * specifically to render this failure, was always `undefined`. The palette came
 * from whatever the cache held, with no banner, no retry, and no way to force a
 * refetch short of clearing IndexedDB by hand.
 *
 * Two states are now distinguishable and both are rendered here: a total
 * failure (nothing cached) and a stale fallback (something cached, provider
 * unreachable). The second is the one that used to be silent.
 */

const objectInfoState = vi.hoisted(() => ({ current: {} }));

vi.mock('../../hooks/useObjectInfo', () => ({
    useObjectInfo: () => objectInfoState.current,
}));

// The graph itself pulls in reactflow's measurement machinery; the palette
// contract does not depend on it.
vi.mock('reactflow', () => ({
    ReactFlow: () => <div data-testid="reactflow" />,
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
    Handle: () => null,
    Position: { Left: 'left', Right: 'right' },
    useReactFlow: () => ({ screenToFlowPosition: () => ({ x: 0, y: 0 }) }),
    ReactFlowProvider: ({ children }) => children,
    addEdge: (a) => a,
    useNodesState: () => [[], vi.fn()],
    useEdgesState: () => [[], vi.fn()],
}));

import ReactFlowEditor from './ReactFlowEditor';

const VALID = {
    KSampler: { category: 'latent', output_node: false },
    CheckpointLoaderSimple: { category: 'loaders', output_node: true },
};

const baseState = (overrides = {}) => ({
    data: VALID,
    isLoading: false,
    error: null,
    isStale: false,
    staleData: null,
    refetch: vi.fn(),
    isFetching: false,
    ...overrides,
});

function renderEditor() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
        <QueryClientProvider client={queryClient}>
            <ReactFlowEditor providerId="prov-1" onGraphChange={vi.fn()} />
        </QueryClientProvider>
    );
}

describe('ReactFlowEditor node-palette states', () => {
    beforeEach(() => { objectInfoState.current = baseState(); });

    it('renders the palette with no banner when the load succeeded', () => {
        renderEditor();
        expect(screen.queryByRole('alert')).toBeNull();
    });

    it('a total failure says so and offers a retry', () => {
        objectInfoState.current = baseState({
            data: undefined,
            error: new Error('Provider prov-1 returned no node definitions'),
            isStale: false,
        });

        renderEditor();

        expect(screen.getByText(/Failed to load node definitions/)).toBeTruthy();
        // The retry the old UI never offered. `refetchOnMount: false` plus a
        // cache-only fallback meant this button was the whole recovery path,
        // and it did not exist.
        expect(screen.getByRole('button', { name: /try again/i })).toBeTruthy();
    });

    it('the retry button calls refetch', () => {
        const refetch = vi.fn();
        objectInfoState.current = baseState({
            data: undefined, error: new Error('boom'), isStale: false, refetch,
        });

        renderEditor();
        fireEvent.click(screen.getByRole('button', { name: /try again/i }));

        expect(refetch).toHaveBeenCalledTimes(1);
    });

    it('a stale fallback renders the palette AND says it may be out of date', () => {
        // The regression: `error` was undefined here, so this state was
        // unreachable and the user got yesterday's nodes with no indication.
        objectInfoState.current = baseState({
            data: undefined,
            error: new Error('502 Bad Gateway'),
            isStale: true,
            staleData: VALID,
        });

        renderEditor();

        const alert = screen.getByRole('alert');
        expect(alert).toHaveTextContent(/last saved node list/i);
        expect(alert).toHaveTextContent(/502 Bad Gateway/);
        // The palette is still usable — a stale list beats no list.
        expect(screen.queryByText(/Failed to load node definitions/)).toBeNull();
    });

    it('the stale banner offers a retry', () => {
        const refetch = vi.fn();
        objectInfoState.current = baseState({
            data: undefined, error: new Error('boom'), isStale: true, staleData: VALID, refetch,
        });

        renderEditor();
        fireEvent.click(screen.getByRole('button', { name: /retry/i }));

        expect(refetch).toHaveBeenCalledTimes(1);
    });

    it('does not show both the stale banner and the total-failure panel', () => {
        objectInfoState.current = baseState({
            data: undefined, error: new Error('boom'), isStale: true, staleData: VALID,
        });

        renderEditor();

        // Mutually exclusive states. Rendering the failure panel over a usable
        // stale palette would take the editor away from the user for no reason.
        expect(screen.queryByText(/Failed to load node definitions/)).toBeNull();
        expect(screen.getAllByRole('alert')).toHaveLength(1);
    });

    it('shows a spinner while loading and nothing else', () => {
        objectInfoState.current = baseState({ data: undefined, isLoading: true });

        renderEditor();
        expect(screen.getByText(/Fetching node definitions/)).toBeTruthy();
        expect(screen.queryByRole('alert')).toBeNull();
    });
});