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

// Mutable so a test can put a realistic number of chats behind the Apply
// target list without a second module mock.
const chatsData = vi.hoisted(() => ({ list: [{ id: 'c-1', name: 'Test Chat' }] }));
vi.mock('../hooks/useChats', () => ({
    useChats: () => ({ data: chatsData.list }),
}));

vi.mock('../hooks/useStories', () => ({
    useStories: () => ({ data: [{ id: 'st-1', title: 'Test Story' }] }),
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

    it('apply opens a modal, picks a target, and calls applyScenario', async () => {
        renderWithProviders(<Scenarios />);
        fireEvent.click(screen.getAllByTitle('Apply to chat or story')[0]);
        expect(screen.getByRole('button', { name: /Test Chat/ })).toBeInTheDocument();
        const targetBtn = screen.getByText('Test Chat');
        fireEvent.click(targetBtn);
        const applyBtn = screen.getByRole('button', { name: /^Apply$/i });
        expect(applyBtn).not.toBeDisabled();
        fireEvent.click(applyBtn);
        expect(mockApplyMutate).toHaveBeenCalledWith(
            { scenarioId: 's-1', targetType: 'chat', targetId: 'c-1' },
            expect.any(Object)
        );
    });

    it('apply with story target uses story mode', async () => {
        renderWithProviders(<Scenarios />);
        fireEvent.click(screen.getAllByTitle('Apply to chat or story')[0]);
        const storyToggle = screen.getByTestId('target-type-story');
        fireEvent.click(storyToggle);
        const targetBtn = screen.getByText('Test Story');
        fireEvent.click(targetBtn);
        fireEvent.click(screen.getByRole('button', { name: /^Apply$/i }));
        expect(mockApplyMutate).toHaveBeenCalledWith(
            { scenarioId: 's-1', targetType: 'story', targetId: 'st-1' },
            expect.any(Object)
        );
    });
});

describe('Scenarios page — finding a target in 200 chats', () => {
    const MANY = Array.from({ length: 30 }, (_, i) => ({
        id: `ch-${i}`,
        name: i === 17 ? 'The Salt Marsh Debrief' : `Chat number ${i}`,
    }));

    beforeEach(() => {
        vi.clearAllMocks();
        mockUseScenarios.mockReturnValue({ data: SAMPLE, isLoading: false });
        mockConfirm.mockResolvedValue(true);
        chatsData.list = [{ id: 'c-1', name: 'Test Chat' }];
    });

    it('narrows the unfiltered target list to the typed query', () => {
        chatsData.list = MANY;
        renderWithProviders(<Scenarios />);
        fireEvent.click(screen.getAllByTitle('Apply to chat or story')[0]);

        // Before typing, the whole list is offered — that is the problem.
        expect(screen.getByText('Chat number 0')).toBeInTheDocument();

        fireEvent.change(screen.getByTestId('apply-target-search'), {
            target: { value: 'salt marsh' },
        });
        expect(screen.queryByText('Chat number 0')).not.toBeInTheDocument();
        expect(screen.getByText('The Salt Marsh Debrief')).toBeInTheDocument();
        expect(screen.getByText('1 of 30 chats shown.')).toBeInTheDocument();
    });

    it('says so when nothing matches, rather than showing an empty box', () => {
        renderWithProviders(<Scenarios />);
        fireEvent.click(screen.getAllByTitle('Apply to chat or story')[0]);
        fireEvent.change(screen.getByTestId('apply-target-search'), {
            target: { value: 'zzzz' },
        });
        expect(screen.getByText(/No chat matches/)).toBeInTheDocument();
    });

    it('clears the search when the target type flips, so a chat query cannot hide every story', () => {
        renderWithProviders(<Scenarios />);
        fireEvent.click(screen.getAllByTitle('Apply to chat or story')[0]);
        fireEvent.change(screen.getByTestId('apply-target-search'), {
            target: { value: 'salt' },
        });
        expect(screen.queryByText('Test Chat')).not.toBeInTheDocument();

        fireEvent.click(screen.getByTestId('target-type-story'));
        expect(screen.getByTestId('apply-target-search')).toHaveValue('');
        expect(screen.getByText('Test Story')).toBeInTheDocument();
    });
});
