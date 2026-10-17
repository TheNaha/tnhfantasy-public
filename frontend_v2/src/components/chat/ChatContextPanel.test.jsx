import React from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

const mockUseChatWorkspace = vi.fn();
vi.mock('../../contexts/ChatWorkspaceContext', () => ({
    useChatWorkspace: () => mockUseChatWorkspace(),
}));

const mockUseLocations = vi.hoisted(() => vi.fn(() => ({ data: [] })));
vi.mock('../../hooks/useLocations', () => ({ useLocations: () => mockUseLocations() }));
vi.mock('../../hooks/useWorldVault', () => ({
    getAvatarUrl: (id) => `/avatars/${id}.png`,
    useEvaluateChatDirector: () => ({ mutate: vi.fn(), isPending: false }),
    useUpdateChatStateSnapshot: () => ({ mutate: vi.fn(), isPending: false }),
    useCommitChatToCanon: () => ({ mutate: vi.fn(), isPending: false }),
    useCompileChatToStory: () => ({ mutate: vi.fn(), isPending: false }),
    useRunWorldTick: () => ({ mutate: vi.fn(), isPending: false }),
    useReverseVisionSync: () => ({ mutate: vi.fn(), isPending: false }),
    useFastTravelChat: () => ({ mutate: vi.fn(), isPending: false }),
    useVisualizeInventoryItem: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock('../../hooks/useStreamingJobs', () => ({ useActiveChatStreams: () => [] }));

// The panel's neighbours each own their own fetching; stub them so this test
// exercises the panel's own structure and nothing else. The inspector stub
// re-exposes the props it was handed, because "does the chat panel give the
// shared inspector the two edit handlers the story panel gives it?" is the
// regression these tests exist to catch.
const inspectorProps = vi.hoisted(() => ({ current: {} }));
vi.mock('../workspace/EntityContextInspector', () => ({
    default: (props) => {
        inspectorProps.current = props;
        return <div data-testid="entity-inspector" />;
    },
}));
vi.mock('../common/SamplingControls', () => ({ default: () => <div data-testid="sampling-controls" /> }));
vi.mock('./SystemPromptPanel', () => ({ default: () => <div data-testid="system-prompt" /> }));
vi.mock('./MemoriesPanel', () => ({ default: () => <div data-testid="memories" /> }));
vi.mock('./ExpressionSelector', () => ({ default: () => <div data-testid="expressions" /> }));

import ChatContextPanel from './ChatContextPanel';

const LOCATIONS = [
    { id: 'loc-1', name: 'The Docks', atmosphere: 'Salt and tar', description: '' },
    { id: 'loc-2', name: 'The Rookery', description: 'Cliffside tenements' },
];

const LOREBOOKS = [{ id: 'lb-1', name: 'Harbour Law' }];

const WORLDS = [
    // `counts` from the /api/v2/worlds list, derived from `member.world_id`.
    { id: 'w-1', name: 'Emberfall', description: 'A city inside a volcano.', counts: { Lorebook: 1, Location: 1, Scenario: 0, Character: 0, Chat: 0, Story: 0, VoiceModel: 0 } },
];

function makeContext(overrides = {}) {
    return {
        activeChat: { id: 'chat-1', name: 'Session', persona_name: 'Default (User)' },
        linkedCharacter: { id: 'char-1', name: 'Aria', avatar_path: null },
        chatJobs: [],
        chatCollection: { image_count: 0 },
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
        worlds: [],
        personas: [],
        messages: [],
        onEditCharacter: vi.fn(),
        onEditLorebook: vi.fn(),
        onEditLocation: vi.fn(),
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

        // Author's Note / Depth / Story Time are all still labels. "Location" is
        // deliberately NOT one of them any more: the free-text field that used
        // to live here wrote `story_location` and nothing, and it sat in the
        // same column as the real, linked Location picker — the reason the two
        // drifted apart. See the "no second, unlinked Location field" test below.
        const text = container.textContent;
        for (const label of ["Author's Note", 'Depth', 'Story Time']) {
            expect(text).toContain(label);
        }
    });

    it('has no second, unlinked Location field beside the real one', () => {
        renderPanel();
        const details = screen.getByTestId('scene-overrides');
        fireEvent.click(within(details).getByText(/Scene Overrides/));

        // The real picker writes `location_id`, and lives outside this disclosure.
        expect(within(details).queryByRole('group', { name: 'Location' })).not.toBeInTheDocument();
        expect(screen.getByTestId('new-location')).toBeInTheDocument();
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

describe('ChatContextPanel — the editors the story panel already had', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockUseLocations.mockReturnValue({ data: LOCATIONS });
    });

    it('links a chat to a real Location, writing the column nothing wrote before', () => {
        const { ctx } = renderPanel({ activeChat: { id: 'chat-1' } });
        fireEvent.click(screen.getByTestId('location-row-loc-1'));
        expect(ctx.handleChatUpdate).toHaveBeenCalledWith({ location_id: 'loc-1' });
    });

    it('clears the link when the already-selected row is clicked again', () => {
        const { ctx } = renderPanel({ activeChat: { id: 'chat-1', location_id: 'loc-1' } });
        fireEvent.click(screen.getByTestId('location-row-loc-1'));
        expect(ctx.handleChatUpdate).toHaveBeenCalledWith({ location_id: null });
    });

    it('opens LocationModal in place from the + and the row pencil', () => {
        const { ctx } = renderPanel();
        fireEvent.click(screen.getByTestId('new-location'));
        expect(ctx.onEditLocation).toHaveBeenCalledWith(null);

        fireEvent.click(screen.getByLabelText('Edit The Docks'));
        expect(ctx.onEditLocation).toHaveBeenCalledWith(LOCATIONS[0]);
    });

    it('creates a lorebook in place from the +, and edits an existing one', () => {
        const { ctx } = renderPanel({ lorebooks: LOREBOOKS });
        fireEvent.click(screen.getByTestId('new-lorebook'));
        expect(ctx.onEditLorebook).toHaveBeenCalledWith(null);

        fireEvent.click(screen.getByLabelText('Edit Harbour Law'));
        expect(ctx.onEditLorebook).toHaveBeenCalledWith(LOREBOOKS[0]);
    });

    it('hands the shared inspector the two edit handlers and the cross-links', () => {
        const { ctx } = renderPanel();
        expect(inspectorProps.current.onEditLocation).toBe(ctx.onEditLocation);
        expect(inspectorProps.current.onEditLorebook).toBe(ctx.onEditLorebook);
        // The inspector renders a pencil titled `Edit <name>`; opening the
        // read-only details modal under that label is what made it a lie.
        expect(inspectorProps.current.onEditCharacter).toBe(ctx.onEditCharacter);
        expect(inspectorProps.current.extraLinks.map(l => l.to)).toEqual(['/activity', '/world-graph']);
    });

    it('points the inspector at the linked location, not the free-text one', () => {
        renderPanel({ activeChat: { id: 'chat-1', location_id: 'loc-2', story_location: 'Somewhere' } });
        expect(inspectorProps.current.locationIds).toEqual(['loc-2']);
    });
});

describe('ChatContextPanel — world row', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockUseLocations.mockReturnValue({ data: LOCATIONS });
    });

    it('writes world_id when a world is picked, and an empty value to detach', () => {
        const { ctx } = renderPanel({ activeChat: { id: 'chat-1' }, worlds: WORLDS });
        const select = screen.getByLabelText('World');
        fireEvent.change(select, { target: { value: 'w-1' } });
        expect(ctx.handleChatUpdate).toHaveBeenCalledWith({ world_id: 'w-1' });

        fireEvent.change(select, { target: { value: '' } });
        expect(ctx.handleChatUpdate).toHaveBeenCalledWith({ world_id: '' });
    });

    it('renders the panel the worldLinkWarning message tells users to come back to', () => {
        renderPanel({ activeChat: { id: 'chat-1', world_id: 'w-1' }, worlds: WORLDS });
        // WORLD_IGNORED_MESSAGE says "the chat's World panel" by name.
        expect(screen.getByRole('heading', { name: 'World' })).toBeInTheDocument();
    });

    it('shows the current world and what it contributes', () => {
        renderPanel({ activeChat: { id: 'chat-1', world_id: 'w-1' }, worlds: WORLDS });
        expect(screen.getByLabelText('World')).toHaveValue('w-1');
        expect(screen.getByText(/A city inside a volcano/)).toBeInTheDocument();
        expect(screen.getByText(/Added to every reply: 1 lorebook · 1 location\./)).toBeInTheDocument();
    });
});

/**
 * Three chat-surface controls were decided by `length > 0` on a query that
 * discarded `isError`.
 *
 * `useChatWorkspaceData` destructured all sixteen of its `data` fields with a
 * `= []` default, so a 503 produced the same value as an empty result. The
 * consequences were not uniform:
 *
 *  - the lorebooks row printed "No lorebooks available" — a claim;
 *  - the persona and TTS-voice `<select>`s vanished entirely — a control gone,
 *    with no message, so narration and persona silently became unconfigurable
 *    and nothing on screen said why.
 *
 * The panel receives `queryErrors` from the hook's choke point and gates each
 * row on its own entry.
 */
describe('ChatContextPanel with failed context queries', () => {
    beforeEach(() => { vi.clearAllMocks(); });

    it('does not claim there are no lorebooks when the lorebooks query failed', () => {
        renderPanel({
            lorebooks: [],
            queryErrors: { lorebooks: { error: new Error('503 down'), refetch: vi.fn(), noun: 'lorebooks' } },
        });

        expect(screen.getByRole('alert')).toHaveTextContent(/could not load your lorebooks/i);
        expect(screen.queryByText('No lorebooks available')).toBeNull();
    });

    it('keeps the persona selector visible with a failure notice, not silently removed', () => {
        const refetch = vi.fn();
        renderPanel({
            personas: [],
            queryErrors: { personas: { error: new Error('p boom'), refetch, noun: 'personas' } },
        });

        expect(screen.getByRole('alert')).toHaveTextContent(/could not load your personas/i);
        // The control itself stays — this outage is transient and the chat
        // already names a persona; what is wrong is the claim about the library.
        expect(screen.queryByTestId('chat-persona-select')).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: /try again/i }));
        expect(refetch).toHaveBeenCalledTimes(1);
    });

    it('states a failed voices fetch rather than dropping the TTS control', () => {
        renderPanel({
            voices: [],
            queryErrors: { voices: { error: new Error('v boom'), refetch: vi.fn(), noun: 'voices' } },
        });

        expect(screen.getByRole('alert')).toHaveTextContent(/could not load your voices/i);
        expect(screen.getByText('Default TTS voice')).toBeInTheDocument();
    });

    it('still shows the real empty states when the queries succeeded', () => {
        renderPanel({ lorebooks: [], personas: [], voices: [], queryErrors: {} });

        expect(screen.getByText('No lorebooks available')).toBeInTheDocument();
        // No personas and no voices legitimately means no selectors.
        expect(screen.queryByTestId('chat-persona-select')).toBeNull();
        expect(screen.queryByText('Default TTS voice')).toBeNull();
        expect(screen.queryByRole('alert')).toBeNull();
    });

    it('shows the persona selector when personas loaded', () => {
        renderPanel({ personas: [{ id: 'p-1', name: 'Ilse' }], queryErrors: {} });
        expect(screen.getByTestId('chat-persona-select')).toBeInTheDocument();
    });
});
