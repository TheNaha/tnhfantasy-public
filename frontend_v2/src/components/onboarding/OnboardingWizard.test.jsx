import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClientProvider, QueryClient } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import OnboardingWizard from './OnboardingWizard';
import { SETUP_COMPLETE_KEY, isSetupComplete, markSetupComplete } from '../../utils/setupComplete';

const mockNavigate = vi.hoisted(() => vi.fn());

vi.mock('react-router-dom', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../../api', () => ({
    api: {
        get: vi.fn(() => Promise.resolve({ data: { templates: [] } })),
    },
}));

vi.mock('../../hooks/useProvidersPageData', () => ({
    default: () => ({ providers: [], isLoading: false }),
}));

vi.mock('../../hooks/useModelDirectories', () => ({
    useModelDirectories: () => ({ modelsByKey: { checkpoints: [] }, loading: false }),
}));

vi.mock('react-hot-toast', () => ({
    default: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('framer-motion', () => ({
    motion: {
        div: ({ children, ...props }) => {
            const safe = {};
            for (const k of Object.keys(props)) {
                if (!['initial', 'animate', 'exit', 'whileHover', 'whileTap', 'transition', 'variants', 'layout'].includes(k)) {
                    safe[k] = props[k];
                }
            }
            return <div {...safe}>{children}</div>;
        },
    },
}));

function renderWizard(props = {}) {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: { retry: false },
        },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter>
                <OnboardingWizard onClose={props.onClose || (() => {})} />
            </MemoryRouter>
        </QueryClientProvider>
    );
}

describe('setup-complete flag', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        localStorage.clear();
    });

    it('returns false when the flag is absent or not true', () => {
        expect(isSetupComplete()).toBe(false);
        localStorage.setItem(SETUP_COMPLETE_KEY, JSON.stringify('yes'));
        expect(isSetupComplete()).toBe(false);
        localStorage.setItem(SETUP_COMPLETE_KEY, '{not json');
        expect(isSetupComplete()).toBe(false);
    });

    it('returns true when the flag is JSON true', () => {
        localStorage.setItem(SETUP_COMPLETE_KEY, JSON.stringify(true));
        expect(isSetupComplete()).toBe(true);
    });

    it('markSetupComplete persists the flag', () => {
        markSetupComplete();
        expect(localStorage.getItem(SETUP_COMPLETE_KEY)).toBe(JSON.stringify(true));
        expect(isSetupComplete()).toBe(true);
    });
});

describe('OnboardingWizard', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        localStorage.clear();
    });

    it('walks through all steps and finishes', () => {
        const onClose = vi.fn();
        renderWizard({ onClose });

        expect(screen.getByText('Welcome to your Fantasy Engine')).toBeInTheDocument();

        fireEvent.click(screen.getByText('Continue'));
        expect(screen.getByText('Choose a world template')).toBeInTheDocument();

        fireEvent.click(screen.getByText('Continue'));
        expect(screen.getByText('Connect a provider')).toBeInTheDocument();

        fireEvent.click(screen.getByText('Continue'));
        expect(screen.getByText('Install a checkpoint')).toBeInTheDocument();

        fireEvent.click(screen.getByText('Continue'));
        expect(screen.getByText("You're ready")).toBeInTheDocument();

        fireEvent.click(screen.getByText('Finish'));
        expect(isSetupComplete()).toBe(true);
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('skip marks setup complete and closes', () => {
        const onClose = vi.fn();
        renderWizard({ onClose });
        fireEvent.click(screen.getByText('Skip'));
        expect(isSetupComplete()).toBe(true);
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('dismiss X marks setup complete and closes', () => {
        const onClose = vi.fn();
        renderWizard({ onClose });
        fireEvent.click(screen.getByLabelText('Dismiss onboarding'));
        expect(isSetupComplete()).toBe(true);
        expect(onClose).toHaveBeenCalledTimes(1);
    });



    it('back button returns to the previous step', () => {
        renderWizard();
        fireEvent.click(screen.getByText('Continue'));
        expect(screen.getByText('Choose a world template')).toBeInTheDocument();
        fireEvent.click(screen.getByText('Back'));
        expect(screen.getByText('Welcome to your Fantasy Engine')).toBeInTheDocument();
        expect(screen.getByText('Back')).toBeDisabled();
    });

    it('add-manually link navigates to providers page', () => {
        renderWizard();
        fireEvent.click(screen.getByText('Continue'));
        fireEvent.click(screen.getByText('Continue'));
        fireEvent.click(screen.getByText('Add a provider manually'));
        expect(mockNavigate).toHaveBeenCalledWith('/providers');
    });
});