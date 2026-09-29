/**
 * `useUpdatePersona` reporting failure after the write landed.
 *
 * `useUpdateResource` took a `detailQueryKey`, had no default, and called it
 * unconditionally in `onSuccess`. Personas was the only one of six call sites
 * that omitted it, so `detailQueryKey(variables.id)` raised a `TypeError` —
 * but react-query awaits `onSuccess` inside its own `try`, so the TypeError was
 * caught and dispatched as an *error*. The PATCH had already succeeded. The
 * user saw the data save, two red toasts, and an edit form that never closed,
 * and `mutation.isError` was true for a write that had worked.
 *
 * These tests render the real `Personas` page and the real
 * `useUpdateResource`; only the HTTP client is mocked, so reverting the guard
 * in the shared hook fails here.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
}));

const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const confirmMock = vi.hoisted(() => vi.fn());

vi.mock('../api', () => ({ api: apiMock }));
vi.mock('react-hot-toast', () => ({ default: toastMock }));
vi.mock('../store/confirmationStore', () => ({ useConfirmation: () => ({ confirm: confirmMock }) }));

const PERSONAS = [
    { id: 'p-1', name: 'Wanderer', description: 'A traveller with no fixed road' },
    { id: 'p-2', name: 'Archivist', description: 'Collects stories' },
];

async function renderPersonas() {
    const Personas = (await import('./Personas')).default;
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <Personas />
        </QueryClientProvider>,
    );
}

beforeEach(() => {
    vi.clearAllMocks();
    apiMock.get.mockResolvedValue(PERSONAS);
    apiMock.put.mockResolvedValue({ ...PERSONAS[0], name: 'Wanderer the Bold' });
    apiMock.post.mockResolvedValue({ id: 'p-3' });
    apiMock.delete.mockResolvedValue({});
    confirmMock.mockResolvedValue(true);
});

describe('useUpdatePersona — a successful write is reported as a success', () => {
    it('closes the edit form and toasts success, with no error toast', async () => {
        await renderPersonas();
        await screen.findByText('Wanderer');

        fireEvent.click(screen.getByTitle('Edit Wanderer'));
        expect(await screen.findByPlaceholderText('Who are you in the story?')).toHaveValue('Wanderer');

        fireEvent.change(screen.getByPlaceholderText('Who are you in the story?'), { target: { value: 'Wanderer the Bold' } });
        fireEvent.click(screen.getByTestId('persona-save-btn'));

        // The form closing is the assertion that matters: it only happens after
        // `onSuccess` runs to completion, and before the fix `onSuccess` threw.
        await waitFor(() => {
            expect(screen.queryByPlaceholderText('Who are you in the story?')).not.toBeInTheDocument();
        });

        expect(apiMock.put).toHaveBeenCalledWith('/api/v2/personas/p-1', expect.objectContaining({
            name: 'Wanderer the Bold',
        }));
        expect(toastMock.success).toHaveBeenCalledWith('Persona updated');
        expect(toastMock.error).not.toHaveBeenCalled();
    });

    it('reports the failure only when the write itself failed', async () => {
        apiMock.put.mockRejectedValue(Object.assign(new Error('nope'), { status: 400 }));
        await renderPersonas();
        await screen.findByText('Wanderer');

        fireEvent.click(screen.getByTitle('Edit Wanderer'));
        fireEvent.change(screen.getByPlaceholderText('Who are you in the story?'), { target: { value: 'Broken' } });
        fireEvent.click(screen.getByTestId('persona-save-btn'));

        await waitFor(() => expect(toastMock.error).toHaveBeenCalled());
        expect(toastMock.success).not.toHaveBeenCalled();
        // The form stays open so the edit is not lost.
        expect(screen.getByPlaceholderText('Who are you in the story?')).toBeInTheDocument();
    });
});

describe('useUpdateResource — an omitted detailQueryKey is not a crash', () => {
    it('invalidates the list and the vault aggregates for a resource with no detail query', async () => {
        const { useUpdatePersona } = await import('../hooks/usePersonas');
        const { TIMELINE_KEY } = await import('../hooks/useTimeline');
        const { buildQueryKey, QUERY_KEYS } = await import('../constants/queryKeys');

        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
        // Seeded rather than spied: an `invalidateQueries` call with a key that
        // matches nothing would pass a spy assertion and change nothing.
        queryClient.setQueryData(buildQueryKey(QUERY_KEYS.PERSONAS), PERSONAS);
        queryClient.setQueryData([...TIMELINE_KEY, {}], { events: [] });
        queryClient.setQueryData(buildQueryKey(QUERY_KEYS.DASHBOARD), { counts: {} });

        const { renderHook } = await import('@testing-library/react');
        const { createElement } = await import('react');
        const { act } = await import('@testing-library/react');
        const { result } = renderHook(() => useUpdatePersona(), {
            wrapper: ({ children }) => createElement(QueryClientProvider, { client: queryClient }, children),
        });

        await act(async () => {
            await result.current.mutateAsync({ id: 'p-1', name: 'Wanderer the Bold' });
        });

        expect(result.current.isError).toBe(false);
        expect(queryClient.getQueryState(buildQueryKey(QUERY_KEYS.PERSONAS))?.isInvalidated).toBe(true);
        expect(queryClient.getQueryState([...TIMELINE_KEY, {}])?.isInvalidated).toBe(true);
        expect(queryClient.getQueryState(buildQueryKey(QUERY_KEYS.DASHBOARD))?.isInvalidated).toBe(true);
    });

    it('still invalidates a detail query when the caller does supply one', async () => {
        const { useUpdateLocation } = await import('../hooks/useLocations');
        const { buildQueryKey, QUERY_KEYS } = await import('../constants/queryKeys');

        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
        queryClient.setQueryData(buildQueryKey(QUERY_KEYS.LOCATIONS), []);
        queryClient.setQueryData(buildQueryKey(QUERY_KEYS.LOCATIONS, 'loc-1'), { id: 'loc-1', name: 'Cinderfall' });

        const { renderHook, act } = await import('@testing-library/react');
        const { createElement } = await import('react');
        const { result } = renderHook(() => useUpdateLocation(), {
            wrapper: ({ children }) => createElement(QueryClientProvider, { client: queryClient }, children),
        });

        await act(async () => {
            await result.current.mutateAsync({ id: 'loc-1', name: 'New name' });
        });

        expect(result.current.isError).toBe(false);
        expect(queryClient.getQueryState(buildQueryKey(QUERY_KEYS.LOCATIONS))?.isInvalidated).toBe(true);
        expect(queryClient.getQueryState(buildQueryKey(QUERY_KEYS.LOCATIONS, 'loc-1'))?.isInvalidated).toBe(true);
    });
});
