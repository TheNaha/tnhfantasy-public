import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Scenarios from './Scenarios';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
Element.prototype.scrollIntoView = vi.fn();

const mockUseScenarios = vi.hoisted(() => vi.fn());
// Mutation `mutate` fns must replay React Query's onSuccess callback so the
// page's toast assertions are observable (the page calls mutate(vars, {onSuccess}).
const mutator = vi.hoisted(() => ({
    make: (ret = {}) => vi.fn(async (vars, opts) => { opts?.onSuccess?.(ret); return ret; }),
}));
const mockCreateMutate = mutator.make();
const mockUpdateMutate = mutator.make();
const mockDeleteMutate = mutator.make();
const mockApplyMutate = mutator.make();
const mockConfirm = vi.hoisted(() => vi.fn().mockResolvedValue(true));

vi.mock('../hooks/useWorldVault', () => ({
    useScenarios: (...a) => mockUseScenarios(...a),
    useCreateScenario: () => ({ mutate: mockCreateMutate }),
    useUpdateScenario: () => ({ mutate: mockUpdateMutate }),
    useDeleteScenario: () => ({ mutate: mockDeleteMutate }),
    useApplyScenario: () => ({ mutate: mockApplyMutate }),
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
    { id: 's-1', name: 'Tavern Brawl', description: 'A rowdy drinking hall', prompt_template: 'You are a barkeep.', default_checkpoint: '', default_voice_profile: '' },
    { id: 's-2', name: 'Royal Court', description: '', prompt_template: '', default_checkpoint: 'anything-v5', default_voice_profile: 'en_speaker_02' },
];

describe('Scenarios page', () => {
    let toastMock;

    beforeEach(() => {
        vi.clearAllMocks();
        mockUseScenarios.mockReturnValue({ data: SAMPLE, isLoading: false });
        mockConfirm.mockResolvedValue(true);
        import('react-hot-toast').then((m) => (toastMock = m.default));
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('renders heading and create button', () => {
        renderWithProviders(<Scenarios />);
        expect(screen.getByRole('heading', { name: 'Scenarios' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /create scenario/i })).toBeInTheDocument();
    });

    it('shows empty state when no scenarios', () => {
        mockUseScenarios.mockReturnValue({ data: [], isLoading: false });
        renderWithProviders(<Scenarios />);
        expect(screen.getByText(/no scenarios yet/i)).toBeInTheDocument();
    });

    it('renders a card per scenario with name, description and template', () => {
        renderWithProviders(<Scenarios />);
        expect(screen.getByText('Tavern Brawl')).toBeInTheDocument();
        expect(screen.getByText('Royal Court')).toBeInTheDocument();
        expect(screen.getByText('A rowdy drinking hall')).toBeInTheDocument();
        expect(screen.getByText('You are a barkeep.')).toBeInTheDocument();
        expect(screen.getAllByTitle('Apply to chat or story')).toHaveLength(SAMPLE.length);
    });

    it('create validates name is required without calling mutate', () => {
        renderWithProviders(<Scenarios />);
        fireEvent.click(screen.getByRole('button', { name: /create scenario/i }));
        fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
        expect(toastMock.error).toHaveBeenCalledWith('Name is required');
        expect(mockCreateMutate).not.toHaveBeenCalled();
    });

    it('create submits formData with the entered name and shows success', async () => {
        renderWithProviders(<Scenarios />);
        fireEvent.click(screen.getByRole('button', { name: /create scenario/i }));
        fireEvent.change(screen.getByPlaceholderText('Scenario name'), { target: { value: 'New Scenario' } });
        fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
        await waitFor(() => expect(mockCreateMutate).toHaveBeenCalledWith(
            expect.objectContaining({ name: 'New Scenario' }),
            expect.any(Object)
        ));
        await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Scenario created'));
    });

    it('edit prefills the form and updates on save', async () => {
        renderWithProviders(<Scenarios />);
        fireEvent.click(screen.getAllByTitle('Edit')[0]);
        await waitFor(() => screen.getByDisplayValue('Tavern Brawl'));
        expect(screen.getByPlaceholderText('Scenario name')).toHaveValue('Tavern Brawl');
        fireEvent.change(screen.getByPlaceholderText('Scenario name'), { target: { value: 'Tavern Brawl II' } });
        fireEvent.click(screen.getByRole('button', { name: /^update$/i }));
        expect(mockUpdateMutate).toHaveBeenCalledWith(
            expect.objectContaining({ id: 's-1', name: 'Tavern Brawl II' }),
            expect.any(Object)
        );
        await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Scenario updated'));
    });

    it('delete confirms with message and removes on confirm', async () => {
        renderWithProviders(<Scenarios />);
        fireEvent.click(screen.getAllByTitle('Delete')[0]);
        expect(mockConfirm).toHaveBeenCalledWith(expect.objectContaining({
            title: 'Delete Scenario',
            confirmText: 'Delete',
            isDangerous: true,
        }));
        await waitFor(() => expect(mockDeleteMutate).toHaveBeenCalledWith('s-1', expect.any(Object)));
        await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Scenario deleted'));
    });

    it('delete without confirmation does not call mutate', () => {
        mockConfirm.mockResolvedValue(false);
        renderWithProviders(<Scenarios />);
        fireEvent.click(screen.getAllByTitle('Delete')[0]);
        expect(mockDeleteMutate).not.toHaveBeenCalled();
    });

    it('apply prompts for target type and calls applyScenario', async () => {
        let calls = 0;
        vi.stubGlobal('prompt', () => (calls++ === 0 ? 'chat' : 'target-1'));
        renderWithProviders(<Scenarios />);
        fireEvent.click(screen.getAllByTitle('Apply to chat or story')[0]);
        expect(mockApplyMutate).toHaveBeenCalledWith(
            { scenarioId: 's-1', targetType: 'chat', targetId: 'target-1' },
            expect.any(Object)
        );
    });
});
