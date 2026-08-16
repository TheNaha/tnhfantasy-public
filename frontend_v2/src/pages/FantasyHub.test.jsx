import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import FantasyHub from './FantasyHub';

const mockNavigate = vi.hoisted(() => vi.fn());

vi.mock('react-router-dom', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('framer-motion', () => ({
    AnimatePresence: ({ children }) => <>{children}</>,
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

function renderPage() {
    return render(
        <MemoryRouter>
            <FantasyHub />
        </MemoryRouter>
    );
}

describe('FantasyHub page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        localStorage.setItem('tnhcomfy_setup_complete', 'true');
    });

    it('renders the main heading and tagline', () => {
        renderPage();
        expect(screen.getByRole('heading', { name: 'Fantasy Hub' })).toBeInTheDocument();
        expect(screen.getByText('Your comprehensive AI fantasy engine. Choose a workspace to begin creating.')).toBeInTheDocument();
    });

    it('renders all six workspace cards', () => {
        renderPage();
        expect(screen.getAllByText('Image Generation').length).toBeGreaterThan(0);
        expect(screen.getAllByText('Roleplay Chat').length).toBeGreaterThan(0);
        expect(screen.getAllByText('Story Sandbox').length).toBeGreaterThan(0);
        expect(screen.getAllByText('World Vault').length).toBeGreaterThan(0);
        expect(screen.getByText('Scenarios')).toBeInTheDocument();
        expect(screen.getByText('Voice Models')).toBeInTheDocument();
        expect(screen.getByText('Define reusable prompt templates and world settings. Apply them to chats and stories with one click.')).toBeInTheDocument();
        expect(screen.getAllByText('Enter workspace')).toHaveLength(6);
    });

    it('renders the feature footer items', () => {
        renderPage();
        expect(screen.getByText('Unified asset library')).toBeInTheDocument();
        expect(screen.getByText('Agentic AI workflows')).toBeInTheDocument();
    });

    it('navigates to the correct workspace when a card is clicked', () => {
        renderPage();
        fireEvent.click(screen.getAllByText('Story Sandbox')[0]);
        expect(mockNavigate).toHaveBeenCalledWith('/story');
        fireEvent.click(screen.getAllByText('Image Generation')[0]);
        expect(mockNavigate).toHaveBeenCalledWith('/generate');
        fireEvent.click(screen.getByText('Voice Models'));
        expect(mockNavigate).toHaveBeenCalledWith('/voices');
        fireEvent.click(screen.getByText('Scenarios'));
        expect(mockNavigate).toHaveBeenCalledWith('/scenarios');
    });

    it('renders quick-action tiles and navigates from them', () => {
        renderPage();
        expect(screen.getByText('New Chat')).toBeInTheDocument();
        expect(screen.getByText('Write a Story')).toBeInTheDocument();
        expect(screen.getByText('Pick a Scenario')).toBeInTheDocument();
        fireEvent.click(screen.getByText('New Chat'));
        expect(mockNavigate).toHaveBeenCalledWith('/chat?new=1');
        fireEvent.click(screen.getByText('Write a Story'));
        expect(mockNavigate).toHaveBeenCalledWith('/story');
        fireEvent.click(screen.getByText('Pick a Scenario'));
        expect(mockNavigate).toHaveBeenCalledWith('/scenarios');
    });
});