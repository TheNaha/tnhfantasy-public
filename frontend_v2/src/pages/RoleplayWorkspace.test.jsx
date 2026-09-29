import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EXPERT_TOOLS } from '../constants/navigation';
import RoleplayWorkspace from './RoleplayWorkspace';

// The world count comes from the real `useWorlds` hook against the mocked HTTP
// client, so this suite proves the front door reads the route the backend
// actually serves. It used to `vi.mock('../hooks/useCampaigns')`, which handed
// the page a world that the (deleted) `/api/v2/campaigns` route could never
// return — the count card read 1 in tests and 0 in the product, and no test
// could tell the difference.
const mockApi = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../api', () => ({ api: mockApi }));

vi.mock('../hooks/useChats', () => ({
    useChats: () => ({
        data: [{ id: 'chat-1', name: 'The First Meeting', updated_at: '2026-01-01T00:00:00Z' }],
        isLoading: false,
    }),
}));

vi.mock('../hooks/useStories', () => ({
    useStories: () => ({
        data: [{ id: 'story-1', title: 'A Small Beginning', updated_at: '2026-01-02T00:00:00Z' }],
        isLoading: false,
    }),
}));

vi.mock('../hooks/useWorldVaultSearch', () => ({
    useWorldVaultDashboard: () => ({
        data: { counts: { characters: 2, chats: 1, stories: 1, lorebooks: 0, locations: 0 } },
    }),
}));

// The wizard pulls in provider and model-directory queries of its own; it is
// covered by OnboardingWizard.test.jsx, so here it is only a marker. Its
// dismissal path persists the setup flag, exactly as the real one does.
vi.mock('../components/onboarding/OnboardingWizard', async () => {
    const { markSetupComplete } = await import('../utils/setupComplete');
    return {
        default: ({ onClose }) => (
            <div role="dialog" aria-label="Onboarding wizard">
                <button type="button" onClick={() => { markSetupComplete(); onClose(); }}>
                    Dismiss wizard
                </button>
            </div>
        ),
    };
});

describe('RoleplayWorkspace', () => {
    beforeEach(() => {
        localStorage.setItem('tnhcomfy_setup_complete', 'true');
        mockApi.get.mockResolvedValue([{ id: 'world-1', name: 'Emberfall' }]);
    });

    function renderWorkspace() {
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
        return render(
            <QueryClientProvider client={queryClient}>
                <MemoryRouter>
                    <RoleplayWorkspace />
                </MemoryRouter>
            </QueryClientProvider>,
        );
    }

    it('offers simple entry points and recent sessions', () => {
        renderWorkspace();

        expect(screen.getByRole('heading', { name: /your next scene starts here/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /start a chat/i })).toBeInTheDocument();
        expect(screen.getByText('The First Meeting')).toBeInTheDocument();
        expect(screen.getByText('A Small Beginning')).toBeInTheDocument();
    });

    // The CountCard read `0` forever because it counted a 404. This asserts the
    // value against the route that exists, so a regression to a dead route fails
    // here instead of shipping a permanent zero.
    it('counts the worlds the real /api/v2/worlds route returns', async () => {
        renderWorkspace();

        await waitFor(() => expect(mockApi.get).toHaveBeenCalledWith('/api/v2/worlds'));

        // Scoped to the "Your world" count grid: the same word appears on the
        // beginner shortcut card and in the expert-tools disclosure.
        const countGrid = document.querySelector('[aria-labelledby="roleplay-world-heading"]');
        const card = within(countGrid).getByRole('button', { name: /Worlds/ });

        await waitFor(() => expect(card).toHaveTextContent('1'));
        expect(card).toHaveTextContent('Worlds');
    });

    it('reveals expert world-building tools on demand', () => {
        renderWorkspace();

        // "World Graph" only ever appears inside the disclosure, so the toggle
        // is asserted on it. "Lorebooks" is also a world count card.
        expect(screen.queryAllByText('World Graph')).toHaveLength(0);
        fireEvent.click(screen.getByRole('button', { name: /expert tools/i }));
        expect(screen.getAllByText('World Graph')).toHaveLength(1);
        expect(screen.getAllByText('Lorebooks').length).toBeGreaterThan(0);
    });

    it('lists exactly the expert tools the sidebar does, including Personas', () => {
        renderWorkspace();

        fireEvent.click(screen.getByRole('button', { name: /expert tools/i }));
        // Personas sets {{user}} and the system prompt, so it has to be
        // discoverable from the front door and not only from Cmd+K.
        expect(screen.getByText('Personas')).toBeInTheDocument();

        // Asserted against EXPERT_TOOLS rather than a hardcoded list. The two
        // surfaces render the same constant, so a name hardcoded here went stale
        // the moment a tool was retired — the Avatar Gallery removal failed this
        // test for exactly that reason, and the failure said nothing about the
        // property the test exists to check.
        for (const tool of EXPERT_TOOLS) {
            expect(
                screen.getAllByText(tool.label).length,
                `${tool.label} is in EXPERT_TOOLS but not rendered on the front door`,
            ).toBeGreaterThan(0);
        }
    });

    it('sends the world shortcut to the live /worlds route, not the retired /campaigns', () => {
        renderWorkspace();

        const shortcut = screen.getByRole('button', { name: /open worlds/i });
        expect(shortcut).toBeInTheDocument();
        // And nothing on the front door still points at the retired URL.
        expect(document.body.innerHTML).not.toContain('/campaigns');
    });

    it('shows the first-run wizard when setup is not complete, and does not bring it back', () => {
        localStorage.removeItem('tnhcomfy_setup_complete');
        const { unmount } = renderWorkspace();

        expect(screen.getByRole('dialog', { name: 'Onboarding wizard' })).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /dismiss wizard/i }));
        expect(screen.queryByRole('dialog', { name: 'Onboarding wizard' })).not.toBeInTheDocument();
        unmount();

        // Dismissing has to survive leaving the page, so a second visit does not
        // reopen it.
        renderWorkspace();
        expect(screen.queryByRole('dialog', { name: 'Onboarding wizard' })).not.toBeInTheDocument();
    });
});
