import React from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

const mockUseChatWorkspace = vi.fn();
vi.mock('../../contexts/ChatWorkspaceContext', () => ({
    useChatWorkspace: () => mockUseChatWorkspace(),
}));

vi.mock('../../hooks/useLocations', () => ({ useLocations: () => ({ data: [] }) }));
vi.mock('../../hooks/useWorldVault', () => ({ getAvatarUrl: (id) => `/avatars/${id}.png` }));

// The panel's neighbours each own their own fetching; stub them so this test
// exercises the panel's own structure and nothing else.
vi.mock('../workspace/EntityContextInspector', () => ({ default: () => <div data-testid="entity-inspector" /> }));
vi.mock('../common/SamplingControls', () => ({ default: () => <div data-testid="sampling-controls" /> }));
vi.mock('./SystemPromptPanel', () => ({ default: () => <div data-testid="system-prompt" /> }));
vi.mock('./MemoriesPanel', () => ({ default: () => <div data-testid="memories" /> }));
vi.mock('./ExpressionSelector', () => ({ default: () => <div data-testid="expressions" /> }));

import ChatContextPanel from './ChatContextPanel';

function makeContext(overrides = {}) {
    return {
        activeChat: { id: 'chat-1', name: 'Session', persona_name: 'Default (User)' },
        linkedCharacter: { id: 'char-1', name: 'Aria', avatar_path: null },
        chatJobs: [],
        chatCollection: { image_count: 0 },
        activeStreamEntries: [],
        sceneJobId: null,
        characters: [{ id: 'char-1', name: 'Aria' }],
        lorebooks: [],
        selectedLorebooks: [],
        patchCharacterMutation: { mutate: vi.fn() },
        systemPromptData: { preview: '' },
        availableModels: [],
        defaultLlmConfig: { model_id: 'default' },
        setShowCharacterDetails: vi.fn(),
        setShowScenesModal: vi.fn(),
        handleChatUpdate: vi.fn(),
        voices: [],
        personas: [],
        messages: [],
        ...overrides,
    };
}

function renderPanel(overrides = {}) {
    const ctx = makeContext(overrides);
    mockUseChatWorkspace.mockReturnValue(ctx);
    const utils = render(<MemoryRouter><ChatContextPanel /></MemoryRouter>);
    return { ...utils, ctx };
}

describe('ChatContextPanel — persona labelling', () => {
    beforeEach(() => { vi.clearAllMocks(); });

    it('says "Your Persona" exactly once — the section header, not the field', () => {
        const { container } = renderPanel();
        const headings = [...container.querySelectorAll('h4')];
        expect(headings.filter((h) => h.textContent.trim() === 'Your Persona')).toHaveLength(1);
        // and the whole panel never spells it twice
        const panel = container.firstElementChild;
        expect(panel.textContent.split('Your Persona').length - 1).toBe(1);
    });

    it('shows the configured persona name in the section, and it stays editable', () => {
        const { ctx } = renderPanel();
        const group = screen.getByRole('group', { name: 'Persona name' });
        expect(within(group).getByText('Default (User)')).toBeInTheDocument();

        fireEvent.click(within(group).getByText('Default (User)'));
        const input = within(group).getByRole('textbox');
        fireEvent.change(input, { target: { value: 'Ilse' } });
        fireEvent.keyDown(input, { key: 'Enter' });
        expect(ctx.handleChatUpdate).toHaveBeenCalledWith({ persona_name: 'Ilse' });
    });

    it('falls back to the placeholder name when the chat has no persona', () => {
        const { container } = renderPanel({ activeChat: { id: 'chat-1' } });
        const group = screen.getByRole('group', { name: 'Persona name' });
        expect(within(group).getByText('Default (User)')).toBeInTheDocument();
        expect(container.textContent.split('Your Persona').length - 1).toBe(1);
    });
});

describe('ChatContextPanel — scene overrides disclosure', () => {
    beforeEach(() => { vi.clearAllMocks(); });

    it('is collapsed by default', () => {
        renderPanel();
        const details = screen.getByTestId('scene-overrides');
        expect(details.open).toBe(false);
    });

    it('keeps every advanced field in the DOM and reachable by opening it', () => {
        const { container } = renderPanel();
        const details = screen.getByTestId('scene-overrides');
        fireEvent.click(within(details).getByText(/Scene Overrides/));
        expect(details.open).toBe(true);

        expect(within(details).getByTestId('authors-note-input')).toBeInTheDocument();
        expect(within(details).getByTestId('authors-note-depth')).toBeInTheDocument();
        expect(within(details).getByRole('group', { name: 'Story Time' })).toBeInTheDocument();
        expect(within(details).getByRole('group', { name: 'Location' })).toBeInTheDocument();

        // Author's Note / Depth / Story Time / Location are all still labels
        const text = container.textContent;
        for (const label of ["Author's Note", 'Depth', 'Story Time', 'Location']) {
            expect(text).toContain(label);
        }
    });

    it('reports how much is configured while collapsed', () => {
        const { unmount } = renderPanel({ activeChat: { id: 'chat-1', story_time: 'Dusk' } });
        expect(screen.getByText('1 set')).toBeInTheDocument();
        unmount();

        renderPanel({
            activeChat: { id: 'chat-1', authors_note: 'Be terse.', story_time: 'Dusk', story_location: 'The Docks' },
        });
        expect(screen.getByText('3 set')).toBeInTheDocument();
    });

    it('saves story time and location through the disclosure', () => {
        const { ctx } = renderPanel();
        const details = screen.getByTestId('scene-overrides');
        fireEvent.click(within(details).getByText(/Scene Overrides/));

        const time = within(details).getByRole('group', { name: 'Story Time' });
        fireEvent.click(within(time).getByText('Not set'));
        fireEvent.change(within(time).getByRole('textbox'), { target: { value: 'Dusk' } });
        fireEvent.keyDown(within(time).getByRole('textbox'), { key: 'Enter' });
        expect(ctx.handleChatUpdate).toHaveBeenCalledWith({ story_time: 'Dusk' });
    });
});

describe('ChatContextPanel — author\'s note help text', () => {
    beforeEach(() => { vi.clearAllMocks(); });

    it('states the full explanation as readable text, not a clipped placeholder', () => {
        const { container } = renderPanel();
        const details = screen.getByTestId('scene-overrides');
        fireEvent.click(within(details).getByText(/Scene Overrides/));

        const textarea = within(details).getByTestId('authors-note-input');
        // short placeholder: a 2-row textarea cannot clip it
        expect(textarea.placeholder.length).toBeLessThan(40);
        expect(textarea).toHaveAttribute('title', expect.stringContaining('survives pruning'));
        // and the same sentence is in the visible help paragraph
        expect(container.textContent).toContain('survives pruning');
        expect(container.textContent).toContain('0 pins the note to the very end');
    });

    it('keeps the author\'s note editable', () => {
        const { ctx } = renderPanel();
        const details = screen.getByTestId('scene-overrides');
        fireEvent.click(within(details).getByText(/Scene Overrides/));
        const textarea = within(details).getByTestId('authors-note-input');
        fireEvent.change(textarea, { target: { value: 'Stay in character.' } });
        fireEvent.blur(textarea);
        expect(ctx.handleChatUpdate).toHaveBeenCalledWith({ authors_note: 'Stay in character.' });
    });
});
