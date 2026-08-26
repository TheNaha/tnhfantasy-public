import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Personas from './Personas';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
Element.prototype.scrollIntoView = vi.fn();

const mockUsePersonas = vi.hoisted(() => vi.fn());
// Mutation `mutate` fns must replay React Query's onSuccess callback so the
// page's toast assertions are observable (the page calls mutate(vars, {onSuccess}).
const mutator = vi.hoisted(() => ({
    make: (ret = {}) => vi.fn(async (vars, opts) => { opts?.onSuccess?.(ret); return ret; }),
}));
const mockCreateMutate = mutator.make();
const mockUpdateMutate = mutator.make();
const mockDeleteMutate = mutator.make();
const mockConfirm = vi.hoisted(() => vi.fn().mockResolvedValue(true));

vi.mock('../hooks/useWorldVault', () => ({
    usePersonas: (...a) => mockUsePersonas(...a),
    useCreatePersona: () => ({ mutate: mockCreateMutate }),
    useUpdatePersona: () => ({ mutate: mockUpdateMutate }),
    useDeletePersona: () => ({ mutate: mockDeleteMutate }),
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
    { id: 'p-1', name: 'Ada Vex', description: 'Rogue archaeologist with a silver tongue' },
    { id: 'p-2', name: 'The Narrator', description: '' },
];

describe('Personas page', () => {
    let toastMock;

    beforeEach(() => {
        vi.clearAllMocks();
        mockUsePersonas.mockReturnValue({ data: SAMPLE, isLoading: false });
        mockConfirm.mockResolvedValue(true);
        import('react-hot-toast').then((m) => (toastMock = m.default));
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('renders heading and create button', () => {
        renderWithProviders(<Personas />);
        expect(screen.getByRole('heading', { name: 'Personas' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /create persona/i })).toBeInTheDocument();
    });

    it('shows empty state when no personas', () => {
        mockUsePersonas.mockReturnValue({ data: [], isLoading: false });
        renderWithProviders(<Personas />);
        expect(screen.getByText(/no personas yet/i)).toBeInTheDocument();
    });

    it('renders a row per persona with name and description', () => {
        renderWithProviders(<Personas />);
        expect(screen.getByText('Ada Vex')).toBeInTheDocument();
        expect(screen.getByText('The Narrator')).toBeInTheDocument();
        expect(screen.getByText('Rogue archaeologist with a silver tongue')).toBeInTheDocument();
        expect(screen.getAllByTestId('persona-row')).toHaveLength(SAMPLE.length);
    });

    it('create validates name is required without calling mutate', () => {
        renderWithProviders(<Personas />);
        fireEvent.click(screen.getByRole('button', { name: /create persona/i }));
        fireEvent.click(screen.getByTestId('persona-save-btn'));
        expect(toastMock.error).toHaveBeenCalledWith('Name is required');
        expect(mockCreateMutate).not.toHaveBeenCalled();
    });

    it('create submits formData with the entered name and shows success', async () => {
        renderWithProviders(<Personas />);
        fireEvent.click(screen.getByRole('button', { name: /create persona/i }));
        fireEvent.change(screen.getByPlaceholderText('Who are you in the story?'), { target: { value: 'Kai' } });
        fireEvent.click(screen.getByTestId('persona-save-btn'));
        await waitFor(() => expect(mockCreateMutate).toHaveBeenCalledWith(
            expect.objectContaining({ name: 'Kai' }),
            expect.any(Object)
        ));
        await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Persona created'));
    });

    it('edit prefills the form and updates on save', async () => {
        renderWithProviders(<Personas />);
        fireEvent.click(screen.getByTitle('Edit Ada Vex'));
        await waitFor(() => screen.getByDisplayValue('Ada Vex'));
        expect(screen.getByPlaceholderText('Who are you in the story?')).toHaveValue('Ada Vex');
        fireEvent.change(screen.getByPlaceholderText('Who are you in the story?'), { target: { value: 'Ada Vex II' } });
        fireEvent.click(screen.getByTestId('persona-save-btn'));
        expect(mockUpdateMutate).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'p-1', name: 'Ada Vex II' }),
            expect.any(Object)
        );
        await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Persona updated'));
    });

    it('delete confirms with message and removes on confirm', async () => {
        renderWithProviders(<Personas />);
        fireEvent.click(screen.getByTitle('Delete Ada Vex'));
        expect(mockConfirm).toHaveBeenCalledWith(expect.objectContaining({
            title: 'Delete Persona',
            confirmText: 'Delete',
            isDangerous: true,
        }));
        await waitFor(() => expect(mockDeleteMutate).toHaveBeenCalledWith('p-1', expect.any(Object)));
        await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Persona deleted'));
    });

    it('delete without confirmation does not call mutate', () => {
        mockConfirm.mockResolvedValue(false);
        renderWithProviders(<Personas />);
        fireEvent.click(screen.getByTitle('Delete Ada Vex'));
        expect(mockDeleteMutate).not.toHaveBeenCalled();
    });
});
