import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import ModelTagFilter from './ModelTagFilter';

/**
 * The tag picker marks which tags are the user's own.
 *
 * The distinction exists because the backend refuses to delete a tag it
 * scraped, so "all tags look alike" is a UI that quietly lies about what can be
 * removed. The rule this pins: a tag is marked only when the caller says
 * `source === 'user'`, and nothing else in the panel changes — the picker has no
 * model to attach or delete a tag against, so it never grows a delete control.
 */

describe('ModelTagFilter', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    const openPanel = () => fireEvent.click(screen.getByRole('button', { name: /filter by tag/i }));

    it('marks a tag the caller attributes to the user', () => {
        render(
            <ModelTagFilter
                availableTags={['anime', 'character-x']}
                selectedTags={[]}
                onSelectedTagsChange={() => {}}
                tagSources={{ 'character-x': 'user' }}
            />
        );
        openPanel();

        expect(screen.getByText('yours')).toBeInTheDocument();
        // Exactly one marker, and it is on the right row.
        expect(screen.getAllByText('yours')).toHaveLength(1);
        const marked = screen.getByText('character-x').closest('label');
        expect(marked.textContent).toContain('yours');
        expect(screen.getByText('anime').closest('label').textContent).not.toContain('yours');
    });

    it('marks nothing when provenance is unknown, rather than guessing', () => {
        // A tag with no entry in tagSources is unknown, not known-bad and not
        // known-good. Marking it "yours" would promise a delete the backend
        // will refuse; marking it CivitAI would be a lie the app cannot back.
        render(
            <ModelTagFilter
                availableTags={['anime']}
                selectedTags={[]}
                onSelectedTagsChange={() => {}}
                tagSources={{}}
            />
        );
        openPanel();

        expect(screen.queryByText('yours')).toBeNull();
    });

    it('never renders a delete control, having no model to delete from', () => {
        render(
            <ModelTagFilter
                availableTags={['character-x']}
                selectedTags={[]}
                onSelectedTagsChange={() => {}}
                tagSources={{ 'character-x': 'user' }}
            />
        );
        openPanel();

        expect(screen.queryByRole('button', { name: /^remove tag character-x$/i })).toBeNull();
    });

    it('toggles a tag into and back out of the selection', () => {
        // Controlled, so the assertions describe the round trip a real caller
        // gets rather than a frozen prop.
        function Harness() {
            const [selected, setSelected] = useState(['anime']);
            return (
                <ModelTagFilter
                    availableTags={['anime', 'character-x']}
                    selectedTags={selected}
                    onSelectedTagsChange={setSelected}
                />
            );
        }
        render(<Harness />);
        openPanel();

        fireEvent.click(screen.getByRole('checkbox', { name: /character-x/i }));
        expect(screen.getByRole('checkbox', { name: /character-x/i })).toBeChecked();
        expect(screen.getByRole('checkbox', { name: /anime/i })).toBeChecked();

        fireEvent.click(screen.getByRole('checkbox', { name: /anime/i }));
        expect(screen.getByRole('checkbox', { name: /anime/i })).not.toBeChecked();
        expect(screen.getByRole('checkbox', { name: /character-x/i })).toBeChecked();
    });

    it('points at the model details when there is nothing to filter by yet', () => {
        render(
            <ModelTagFilter availableTags={[]} selectedTags={[]} onSelectedTagsChange={() => {}} />
        );
        openPanel();

        expect(screen.getByText(/no tags on the loaded models yet/i)).toBeInTheDocument();
        expect(screen.getByText(/open a model's details/i)).toBeInTheDocument();
    });
});
