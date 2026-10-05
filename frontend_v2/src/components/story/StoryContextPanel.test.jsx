/**
 * The story context panel's world and scenario rows.
 *
 * `Story.world_id` and `Story.scenario_id` were both written by something
 * (the world by the create form, the scenario by Scenarios → Apply) and read by
 * nothing in the UI. A scenario applied to a story was invisible and impossible
 * to take off, even though `stories.py` injects its `prompt_template` into every
 * continuation.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../workspace/EntityContextInspector', () => ({ default: () => <div data-testid="inspector" /> }));
vi.mock('../common/SamplingControls', () => ({ default: () => <div /> }));
vi.mock('./StoryOutlinePanel', () => ({ default: () => <div data-testid="outline" /> }));

import StoryContextPanel from './StoryContextPanel';

const WORLDS = [
    { id: 'w-1', name: 'Emberfall', description: 'A city inside a volcano.', lorebook_ids: ['lb-1'], location_ids: ['loc-1'], scenario_ids: ['sc-9'] },
    { id: 'w-2', name: 'Hollow Marsh', description: '', lorebook_ids: [], location_ids: [], scenario_ids: [] },
];

const SCENARIOS = [
    { id: 'sc-1', name: 'Tavern Brawl', description: 'A rowdy drinking hall.' },
    { id: 'sc-2', name: 'Royal Court', description: '' },
];

const NOOP = () => {};

function renderPanel(props = {}) {
    const onUpdateStory = props.onUpdateStory || vi.fn();
    const utils = render(
        <StoryContextPanel
            activeStory={{ id: 'story-1', title: 'A Tale' }}
            activeChapter={null}
            characters={[]}
            lorebooks={[]}
            locations={[]}
            storyImages={[]}
            chapters={[]}
            llmModels={[]}
            defaultLlmConfig={null}
            onClose={NOOP}
            onShowGallery={NOOP}
            onUpdateStory={onUpdateStory}
            {...props}
        />
    );
    return { ...utils, onUpdateStory };
}

describe('StoryContextPanel — world row', () => {
    beforeEach(() => vi.clearAllMocks());

    it('writes world_id when a world is chosen, and an empty value to detach', () => {
        const { onUpdateStory } = renderPanel({ worlds: WORLDS });
        fireEvent.change(screen.getByLabelText('World'), { target: { value: 'w-1' } });
        expect(onUpdateStory).toHaveBeenCalledWith({ world_id: 'w-1' });

        fireEvent.change(screen.getByLabelText('World'), { target: { value: '' } });
        expect(onUpdateStory).toHaveBeenCalledWith({ world_id: '' });
    });

    it('renders the panel the worldLinkWarning message tells users to come back to', () => {
        renderPanel({ worlds: WORLDS, activeStory: { id: 'story-1', world_id: 'w-1' } });
        // WORLD_IGNORED_MESSAGE says "the story's World panel" by name.
        expect(screen.getByRole('heading', { name: 'World' })).toBeInTheDocument();
    });

    it('shows the current world and what it contributes', () => {
        renderPanel({ worlds: WORLDS, activeStory: { id: 'story-1', world_id: 'w-1' } });
        expect(screen.getByLabelText('World')).toHaveValue('w-1');
        expect(screen.getByText(/A city inside a volcano/)).toBeInTheDocument();
        expect(screen.getByText(/1 lorebook · 1 location · 1 scenario/)).toBeInTheDocument();
    });
});

describe('StoryContextPanel — scenario row', () => {
    beforeEach(() => vi.clearAllMocks());

    it('shows which scenario Apply attached, and offers to take it off', () => {
        const { onUpdateStory } = renderPanel({
            scenarios: SCENARIOS,
            activeStory: { id: 'story-1', scenario_id: 'sc-1' },
        });
        expect(screen.getByTestId('story-scenario-select')).toHaveValue('sc-1');
        expect(screen.getByText(/Injected into every continuation of this story/)).toBeInTheDocument();
        expect(screen.getByText('A rowdy drinking hall.')).toBeInTheDocument();

        fireEvent.change(screen.getByTestId('story-scenario-select'), { target: { value: '' } });
        expect(onUpdateStory).toHaveBeenCalledWith({ scenario_id: null });
    });

    it('switches to another scenario rather than only creating one', () => {
        const { onUpdateStory } = renderPanel({
            scenarios: SCENARIOS,
            activeStory: { id: 'story-1', scenario_id: 'sc-1' },
        });
        fireEvent.change(screen.getByTestId('story-scenario-select'), { target: { value: 'sc-2' } });
        expect(onUpdateStory).toHaveBeenCalledWith({ scenario_id: 'sc-2' });
    });

    it('flags an applied scenario that has since been deleted from the library', () => {
        renderPanel({
            scenarios: SCENARIOS,
            activeStory: { id: 'story-1', scenario_id: 'sc-gone' },
        });
        expect(screen.getByText(/no longer in the library/)).toBeInTheDocument();
    });

    it('invites a scenario when none is applied', () => {
        renderPanel({ scenarios: SCENARIOS, activeStory: { id: 'story-1' } });
        expect(screen.getByTestId('story-scenario-select')).toHaveValue('');
        expect(screen.getByText(/injected into every continuation/i)).toBeInTheDocument();
    });
});

/**
 * The story surface's copy of the defect fixed in `useChatWorkspaceData.js`.
 *
 * `StorySandbox.jsx` destructured six context queries with a `= []` default and
 * no `isError`, and this panel builds "No lorebooks" / "No locations" straight
 * off those arrays. A 503 therefore told the author of a story built on four
 * lorebooks that they had none — and, for scenarios, removed the control that
 * lets an applied scenario be seen and taken off, which is the entire reason
 * that row exists.
 */
describe('StoryContextPanel with failed context queries', () => {
    it('does not claim there are no lorebooks when the lorebooks query failed', () => {
        renderPanel({
            lorebooks: [],
            queryErrors: { lorebooks: { error: new Error('503 down'), refetch: vi.fn(), noun: 'lorebooks' } },
        });

        expect(screen.getByRole('alert')).toHaveTextContent(/could not load your lorebooks/i);
        expect(screen.queryByText('No lorebooks')).toBeNull();
    });

    it('does not claim there are no locations when the locations query failed', () => {
        renderPanel({
            locations: [],
            queryErrors: { locations: { error: new Error('boom'), refetch: vi.fn(), noun: 'locations' } },
        });

        expect(screen.getByRole('alert')).toHaveTextContent(/could not load your locations/i);
        expect(screen.queryByText('No locations')).toBeNull();
    });

    it('states a failed scenarios fetch instead of hiding the selector', () => {
        renderPanel({
            scenarios: [],
            activeStory: { id: 'story-1', scenario_id: 'sc-gone' },
            queryErrors: { scenarios: { error: new Error('s boom'), refetch: vi.fn(), noun: 'scenarios' } },
        });

        expect(screen.getByRole('alert')).toHaveTextContent(/could not load your scenarios/i);
    });

    it('retries through the entry the failure came from', () => {
        const refetch = vi.fn();
        renderPanel({
            lorebooks: [],
            queryErrors: { lorebooks: { error: new Error('boom'), refetch, noun: 'lorebooks' } },
        });

        fireEvent.click(screen.getByRole('button', { name: /try again/i }));
        expect(refetch).toHaveBeenCalledTimes(1);
    });

    it('still shows the real empty states when the queries succeeded', () => {
        renderPanel({ lorebooks: [], locations: [], scenarios: [], queryErrors: {} });

        expect(screen.getByText('No lorebooks')).toBeInTheDocument();
        expect(screen.getByText('No locations')).toBeInTheDocument();
        expect(screen.queryByRole('alert')).toBeNull();
    });
});
