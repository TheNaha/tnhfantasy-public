import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import StageModeView from './StageModeView';

describe('StageModeView', () => {
    const mockChat = {
        id: 'chat-1',
        name: 'Tavern Encounter',
        story_location: 'The Rusty Anchor Tavern',
        character_id: 'char-1',
        persona_name: 'Wanderer',
        state_snapshot: {
            character_mood: 'warm_affectionate',
            character_expression: 'smiling warmly',
            last_director_decision: {
                suggested_action_chips: ['Order a pint', 'Ask about the rumor', 'Sit quietly'],
            },
        },
    };

    const mockCharacter = {
        id: 'char-1',
        name: 'Lyra',
        avatar_path: '/avatars/lyra.png',
    };

    const mockMessages = [
        { id: 'm-1', role: 'user', content: 'Good evening.' },
        { id: 'm-2', role: 'char', content: 'Welcome traveler, take a seat by the fire.', character_id: 'char-1' },
    ];

    it('renders stage mode with speaker nameplate, dialogue text, and action chips', () => {
        render(
            <StageModeView
                isOpen
                onClose={() => {}}
                messages={mockMessages}
                activeChat={mockChat}
                linkedCharacter={mockCharacter}
                characters={[mockCharacter]}
                chatImages={[]}
                activeStreams={[]}
                onSendMessage={() => {}}
            />
        );

        expect(screen.getByText('Visual Novel Stage')).toBeInTheDocument();
        expect(screen.getByText('Lyra')).toBeInTheDocument();
        expect(screen.getByText('Welcome traveler, take a seat by the fire.')).toBeInTheDocument();
        expect(screen.getByText(/Order a pint/)).toBeInTheDocument();
        expect(screen.getByText(/Ask about the rumor/)).toBeInTheDocument();
    });

    it('sends message when an action chip is clicked', () => {
        const onSendMessage = vi.fn();

        render(
            <StageModeView
                isOpen
                onClose={() => {}}
                messages={mockMessages}
                activeChat={mockChat}
                linkedCharacter={mockCharacter}
                characters={[mockCharacter]}
                chatImages={[]}
                activeStreams={[]}
                onSendMessage={onSendMessage}
            />
        );

        fireEvent.click(screen.getByText(/Order a pint/));
        expect(onSendMessage).toHaveBeenCalledWith('Order a pint');
    });

    it('sends message when user types into stage input and hits Enter', () => {
        const onSendMessage = vi.fn();

        render(
            <StageModeView
                isOpen
                onClose={() => {}}
                messages={mockMessages}
                activeChat={mockChat}
                linkedCharacter={mockCharacter}
                characters={[mockCharacter]}
                chatImages={[]}
                activeStreams={[]}
                onSendMessage={onSendMessage}
            />
        );

        const input = screen.getByPlaceholderText(/respond to lyra/i);
        fireEvent.change(input, { target: { value: 'Thank you kindly.' } });
        fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });

        expect(onSendMessage).toHaveBeenCalledWith('Thank you kindly.');
    });

    it('renders nothing when isOpen is false', () => {
        const { container } = render(
            <StageModeView
                isOpen={false}
                onClose={() => {}}
                messages={mockMessages}
                activeChat={mockChat}
                linkedCharacter={mockCharacter}
            />
        );

        expect(container.firstChild).toBeNull();
    });
});
