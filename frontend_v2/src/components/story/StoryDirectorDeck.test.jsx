import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import StoryDirectorDeck from './StoryDirectorDeck';

describe('StoryDirectorDeck', () => {
    const mockStory = { id: 'story-1', title: 'The Dragon of Ash' };
    const mockChapter = {
        id: 'chap-1',
        title: 'Chapter 1: The Gathering',
        beats: [
            { id: 'b-1', role: 'narrator', content: 'The rain fell heavily against the tavern glass.' },
        ],
    };

    it('renders 3 contextual action cards and Step In button', () => {
        render(
            <StoryDirectorDeck
                activeStory={mockStory}
                activeChapter={mockChapter}
                editorContent="The door creaked open, revealing a shadowy figure in the doorway."
                onSelectChoice={() => {}}
                onStartChat={() => {}}
            />
        );

        expect(screen.getByText("Director's Deck")).toBeInTheDocument();
        expect(screen.getByText('Action')).toBeInTheDocument();
        expect(screen.getByText('Dialogue')).toBeInTheDocument();
        expect(screen.getByText('Discovery')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /step in & play scene/i })).toBeInTheDocument();
    });

    it('invokes onSelectChoice when a choice card is clicked', () => {
        const onSelectChoice = vi.fn();

        render(
            <StoryDirectorDeck
                activeStory={mockStory}
                activeChapter={mockChapter}
                editorContent="The door creaked open."
                onSelectChoice={onSelectChoice}
                onStartChat={() => {}}
            />
        );

        // Click on the first choice card
        const actionCard = screen.getByText('Action').closest('button');
        fireEvent.click(actionCard);

        expect(onSelectChoice).toHaveBeenCalledWith(expect.any(String));
    });

    it('triggers onStartChat when Step In & Play Scene is clicked', () => {
        const onStartChat = vi.fn();

        render(
            <StoryDirectorDeck
                activeStory={mockStory}
                activeChapter={mockChapter}
                editorContent=""
                onSelectChoice={() => {}}
                onStartChat={onStartChat}
            />
        );

        const stepInBtn = screen.getByRole('button', { name: /step in & play scene/i });
        fireEvent.click(stepInBtn);

        expect(onStartChat).toHaveBeenCalledTimes(1);
    });
});
