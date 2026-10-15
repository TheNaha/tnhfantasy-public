/**
 * The World row both context panels now carry.
 *
 * `Chat.world_id` / `Story.world_id` were writable from the new-chat wizard and
 * from nowhere else, so a world could be attached once and never revised, and
 * `worldLinkWarning.js` told a user to go fix it "from the world's World panel"
 * — a panel that did not exist. These tests cover the two halves of the
 * promise: that the world is revisitable from either surface, and that the row
 * says what picking it actually contributes to the prompt.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import WorldLinkRow from './WorldLinkRow';

// `counts` is what the `/api/v2/worlds` list response carries: one grouped
// scan per member table, derived from `member.world_id`. It replaced the
// `lorebook_ids` / `location_ids` / `scenario_ids` arrays that used to sit on
// the world row.
const WORLDS = [
    {
        id: 'w-1',
        name: 'Emberfall',
        description: 'A city built inside a cooling volcano.',
        counts: { Lorebook: 2, Location: 1, Scenario: 3, Character: 0, Chat: 0, Story: 0, VoiceModel: 0 },
    },
    {
        id: 'w-2',
        name: 'Hollow Marsh',
        description: '',
        counts: { Lorebook: 0, Location: 0, Scenario: 0, Character: 0, Chat: 0, Story: 0, VoiceModel: 0 },
    },
];

describe('WorldLinkRow', () => {
    it('writes the chosen world through onChange, and an empty value to detach', () => {
        const onChange = vi.fn();
        render(<WorldLinkRow worldId="w-1" worlds={WORLDS} onChange={onChange} />);

        const select = screen.getByLabelText('World');
        expect(select).toHaveValue('w-1');

        fireEvent.change(select, { target: { value: 'w-2' } });
        expect(onChange).toHaveBeenCalledWith('w-2');

        fireEvent.change(select, { target: { value: '' } });
        expect(onChange).toHaveBeenCalledWith('');
    });

    it('is revisitable — the same select reads back the current world', () => {
        const { rerender } = render(<WorldLinkRow worldId="" worlds={WORLDS} onChange={() => {}} />);
        expect(screen.getByLabelText('World')).toHaveValue('');

        rerender(<WorldLinkRow worldId="w-2" worlds={WORLDS} onChange={() => {}} />);
        expect(screen.getByLabelText('World')).toHaveValue('w-2');
    });

    it('shows the world description and what it contributes to the prompt', () => {
        render(<WorldLinkRow worldId="w-1" worlds={WORLDS} onChange={() => {}} />);
        expect(screen.getByText(/A city built inside a cooling volcano/)).toBeInTheDocument();
        const summary = screen.getByText(/Added to every reply/i);
        expect(summary).toHaveTextContent('2 lorebooks');
        expect(summary).toHaveTextContent('1 location');
        expect(summary).toHaveTextContent('3 scenarios');
    });

    it('says honestly that an empty world contributes only its description', () => {
        render(<WorldLinkRow worldId="w-2" worlds={WORLDS} onChange={() => {}} />);
        expect(screen.getByText(/this world's description/i)).toBeInTheDocument();
        expect(screen.queryByText(/Added to every reply: 0/)).not.toBeInTheDocument();
    });

    it('promises the world can be changed here later — the copy worldLinkWarning relies on', () => {
        render(<WorldLinkRow worldId="" worlds={WORLDS} onChange={() => {}} />);
        expect(screen.getByText(/You can pick, change or drop it here at any time/i)).toBeInTheDocument();
    });

    it('does not render a select at all when there are no worlds to pick from', () => {
        render(<WorldLinkRow worldId="" worlds={[]} onChange={() => {}} />);
        expect(screen.queryByLabelText('World')).not.toBeInTheDocument();
        expect(screen.getByText(/No worlds yet/i)).toBeInTheDocument();
    });
});

/**
 * A failed worlds fetch rendered as "No worlds yet. Create one…".
 *
 * `useWorlds()` destructured `data` with a `= []` default and no `isError`
 * (fixed in `useChatWorkspaceData.js` and, for the story surface, in
 * `StorySandbox.jsx`). The row made it worse than a lie: the `<select>` is
 * gated on `worlds.length > 0`, so the outage also removed the control
 * entirely, and a world *already attached* resolved to `null` — the panel could
 * not describe what was in use.
 *
 * Both context panels pass `queryErrors` down, so this is asserted once here
 * rather than twice per consumer.
 */
describe('WorldLinkRow with a failed worlds fetch', () => {
    const FAILURE = { worlds: { error: new Error('503 Service Unavailable'), refetch: vi.fn(), noun: 'worlds' } };

    it('states the failure instead of claiming there are no worlds', () => {
        render(<WorldLinkRow worldId="w-1" worlds={[]} queryErrors={FAILURE} />);

        const alert = screen.getByRole('alert');
        expect(alert).toHaveTextContent(/could not load your worlds/i);
        expect(alert).toHaveTextContent(/503 Service Unavailable/);
        expect(screen.queryByText(/No worlds yet/)).toBeNull();
    });

    it('offers a retry wired to the worlds refetch', () => {
        const refetch = vi.fn();
        render(
            <WorldLinkRow
                worldId="w-1"
                worlds={[]}
                queryErrors={{ worlds: { error: new Error('boom'), refetch, noun: 'worlds' } }}
            />,
        );

        fireEvent.click(screen.getByRole('button', { name: /try again/i }));
        expect(refetch).toHaveBeenCalledTimes(1);
    });

    it('does not render the picker it cannot populate', () => {
        render(<WorldLinkRow worldId="w-1" worlds={[]} queryErrors={FAILURE} />);
        expect(screen.queryByLabelText('World')).toBeNull();
    });

    it('renders normally when worlds loaded', () => {
        render(<WorldLinkRow worldId="w-1" worlds={WORLDS} queryErrors={{}} />);

        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.getByLabelText('World')).toHaveValue('w-1');
    });
});
