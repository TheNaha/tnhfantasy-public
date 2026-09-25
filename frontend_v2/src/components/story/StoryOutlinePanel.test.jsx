import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import StoryOutlinePanel from './StoryOutlinePanel';

const chapters = [
    {
        id: 'ch-1',
        chapter_number: 1,
        title: 'Arrival',
        content: 'The gate closed behind them with a sound like thunder.',
        beats: [{ id: 'b1' }],
        image_paths: [],
    },
    {
        id: 'ch-2',
        chapter_number: 2,
        title: 'The Long Road',
        content: 'They walked until the sun bled out over the ridge.',
        beats: [],
        image_paths: ['a.png'],
    },
];

function renderPanel(props = {}) {
    const navigate = vi.fn();
    const utils = render(
        <MemoryRouter>
            <StoryOutlinePanel
                storyId="story-1"
                chapters={chapters}
                activeChapterId="ch-2"
                onNavigate={navigate}
                {...props}
            />
        </MemoryRouter>
    );
    return { ...utils, navigate };
}

describe('StoryOutlinePanel', () => {
    it('is collapsed by default and shows the total word count', () => {
        renderPanel();

        expect(screen.getByRole('button', { name: /Story Outline/ })).toHaveAttribute('aria-expanded', 'false');
        expect(screen.queryByText('Arrival')).not.toBeInTheDocument();
        expect(screen.getByText('20 words')).toBeInTheDocument();
    });

    it('lists chapters in order when expanded', () => {
        renderPanel();
        fireEvent.click(screen.getByRole('button', { name: /Story Outline/ }));

        const rows = screen.getAllByRole('button', { name: /Arrival|The Long Road/ });
        expect(rows[0]).toHaveTextContent('Arrival');
        expect(rows[1]).toHaveTextContent('The Long Road');
    });

    it('navigates to a chapter when a row is clicked', () => {
        const { navigate } = renderPanel();
        fireEvent.click(screen.getByRole('button', { name: /Story Outline/ }));

        fireEvent.click(screen.getByRole('button', { name: /Arrival/ }));
        expect(navigate).toHaveBeenCalledWith('/story/story-1/chapter/ch-1');
    });

    it('renders word count goal progress', () => {
        renderPanel({ wordCountGoal: 40 });
        fireEvent.click(screen.getByRole('button', { name: /Story Outline/ }));

        expect(screen.getByText('50% of word count goal')).toBeInTheDocument();
    });

    it('triggers the snapshot handler for the active chapter', () => {
        const onSnapshot = vi.fn();
        renderPanel({ onSnapshot });

        fireEvent.click(screen.getByRole('button', { name: /Snapshot/ }));
        expect(onSnapshot).toHaveBeenCalled();
    });

    it('disables the snapshot button without an active chapter', () => {
        const onSnapshot = vi.fn();
        renderPanel({ activeChapterId: null, onSnapshot });

        const button = screen.getByRole('button', { name: /Snapshot/ });
        expect(button).toBeDisabled();
        fireEvent.click(button);
        expect(onSnapshot).not.toHaveBeenCalled();
    });

    it('disables the snapshot button while a snapshot is pending', () => {
        renderPanel({ onSnapshot: vi.fn(), isSnapshotting: true });
        expect(screen.getByRole('button', { name: /Snapshot/ })).toBeDisabled();
    });

    it('opens the revision history entry point', () => {
        const onOpenRevisions = vi.fn();
        renderPanel({ onOpenRevisions });

        fireEvent.click(screen.getByRole('button', { name: /History/ }));
        expect(onOpenRevisions).toHaveBeenCalled();
    });

    it('shows an empty state when the story has no chapters', () => {
        renderPanel({ chapters: [] });
        fireEvent.click(screen.getByRole('button', { name: /Story Outline/ }));

        expect(screen.getByText(/No chapters yet/)).toBeInTheDocument();
    });
});
