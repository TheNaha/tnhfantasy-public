import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Lorebooks from './Lorebooks';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
Element.prototype.scrollIntoView = vi.fn();

const mutator = vi.hoisted(() => ({
    make: (ret = {}) => {
        const fn = vi.fn(async (vars, opts) => { opts?.onSuccess?.(ret, vars); return ret; });
        return fn;
    },
}));
const mockCreateMutate = mutator.make();
const mockUpdateMutate = mutator.make();
const mockDeleteMutate = mutator.make();
const mockUseLorebooks = vi.hoisted(() => vi.fn());
const mockConfirm = vi.hoisted(() => vi.fn().mockResolvedValue(true));

vi.mock('../hooks/useLorebooks', () => ({
    useLorebooks: (...a) => mockUseLorebooks(...a),
    useCreateLorebook: () => ({ mutate: mockCreateMutate, mutateAsync: mockCreateMutate, isPending: false }),
    useUpdateLorebook: () => ({ mutate: mockUpdateMutate, mutateAsync: mockUpdateMutate, isPending: false }),
    useDeleteLorebook: () => ({ mutate: mockDeleteMutate, mutateAsync: mockDeleteMutate, isPending: false }),
    useLorebookEntries: () => ({ data: [], isLoading: false }),
    useCreateEntry: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
    useUpdateEntry: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
    useDeleteEntry: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useSearchEntries: () => ({ mutate: vi.fn(), data: null, isPending: false }),
    useReindexLorebook: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock('../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: mockConfirm }),
}));

vi.mock('react-hot-toast', () => {
    const toast = vi.fn();
    toast.success = vi.fn();
    toast.error = vi.fn();
    return { default: toast, toast };
});

vi.mock('framer-motion', () => {
    const Passthrough = ({ children, ...props }) => {
        const safe = {};
        for (const k of Object.keys(props)) {
            if (!['initial', 'animate', 'exit', 'whileHover', 'whileTap', 'transition', 'variants', 'layout'].includes(k)) {
                safe[k] = props[k];
            }
        }
        return <div {...safe}>{children}</div>;
    };
    return {
        motion: new Proxy({}, { get: () => Passthrough }),
        AnimatePresence: ({ children }) => <>{children}</>,
    };
});

function renderWithProviders(ui) {
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter>{ui}</MemoryRouter>
        </QueryClientProvider>
    );
}

const SAMPLE = [
    { id: 'lb-1', name: 'World Facts', description: 'General setting lore' },
    { id: 'lb-2', name: 'Character BGs', description: 'Backstories for main cast' },
];

describe('Lorebooks page', () => {
    let toastMock;

    beforeEach(() => {
        vi.clearAllMocks();
        mockUseLorebooks.mockReturnValue({ data: SAMPLE, isLoading: false });
        mockConfirm.mockResolvedValue(true);
        import('react-hot-toast').then((m) => (toastMock = m.default));
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('renders heading and create button', () => {
        renderWithProviders(<Lorebooks />);
        expect(screen.getByRole('heading', { name: 'Lorebooks' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /new lorebook/i })).toBeInTheDocument();
    });

    it('shows empty state when no lorebooks', () => {
        mockUseLorebooks.mockReturnValue({ data: [], isLoading: false });
        renderWithProviders(<Lorebooks />);
        expect(screen.getByText(/no lorebooks yet/i)).toBeInTheDocument();
    });

    it('renders a card per lorebook', () => {
        renderWithProviders(<Lorebooks />);
        expect(screen.getByText('World Facts')).toBeInTheDocument();
        expect(screen.getByText('Character BGs')).toBeInTheDocument();
    });

    it('search filters by name', () => {
        renderWithProviders(<Lorebooks />);
        fireEvent.change(screen.getByPlaceholderText('Search lorebooks...'), { target: { value: 'character' } });
        expect(screen.getByText('Character BGs')).toBeInTheDocument();
        expect(screen.queryByText('World Facts')).not.toBeInTheDocument();
    });

    it('create validates name is required', () => {
        renderWithProviders(<Lorebooks />);
        fireEvent.click(screen.getByRole('button', { name: /new lorebook/i }));
        fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
        expect(toastMock.error).toHaveBeenCalledWith('Name is required');
        expect(mockCreateMutate).not.toHaveBeenCalled();
    });

    it('create submits with name and description', async () => {
        renderWithProviders(<Lorebooks />);
        fireEvent.click(screen.getByRole('button', { name: /new lorebook/i }));
        fireEvent.change(screen.getByPlaceholderText('Lorebook name'), { target: { value: 'New Lorebook' } });
        fireEvent.change(screen.getByPlaceholderText('What does this lorebook cover?'), { target: { value: 'A test' } });
        fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
        await waitFor(() => expect(mockCreateMutate).toHaveBeenCalledWith(
            expect.objectContaining({ name: 'New Lorebook', description: 'A test' })
        ));
        await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Lorebook created'));
    });

    it('opens entry manager when manage button clicked', () => {
        renderWithProviders(<Lorebooks />);
        const manageBtns = screen.getAllByTitle('Manage entries');
        fireEvent.click(manageBtns[0]);
        expect(screen.getByText('World Facts — Entries')).toBeInTheDocument();
    });
});
