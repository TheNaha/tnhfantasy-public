import { render, screen, fireEvent } from '@testing-library/react';
import { DndContext } from '@dnd-kit/core';
import { SortableContext } from '@dnd-kit/sortable';
import { describe, it, expect, vi } from 'vitest';

import CharacterCard, { SortableCharacterCard } from './CharacterCard';

vi.mock('../../hooks/useWorldVault', () => ({
    getAvatarUrl: (id) => `/api/v2/characters/${id}/avatar`,
}));

const character = {
    id: 'c1',
    name: 'Elara Moonwhisper',
    description: 'Elven sorceress',
    personality: 'Curious and bold',
    has_avatar: true,
    visual_tags: ['elf', 'arcane', 'blue hair', 'silver robe', 'moonlit'],
};

const collection = { image_count: 2, images: ['scene_a.png', 'scene_b.png'] };

function renderInDnd(ui) {
    return render(
        <DndContext>
            <SortableContext items={[character.id]}>{ui}</SortableContext>
        </DndContext>
    );
}

describe('CharacterCard (shared by the character vault and the avatar gallery)', () => {
    it('renders identity, scene count and avatar for both call sites', () => {
        render(
            <CharacterCard
                character={character}
                collection={collection}
                onChat={() => {}}
                onOpen={() => {}}
            />
        );

        expect(screen.getByText('Elara Moonwhisper')).toBeInTheDocument();
        expect(screen.getByText('Elven sorceress')).toBeInTheDocument();
        expect(screen.getByText(/Curious and bold/)).toBeInTheDocument();
        expect(screen.getByAltText('Elara Moonwhisper')).toHaveAttribute('src', '/api/v2/characters/c1/avatar');
        expect(screen.getByText('2 scenes')).toBeInTheDocument();
    });

    it('caps the visible tags at 4 and summarises the rest', () => {
        render(<CharacterCard character={character} onChat={() => {}} />);

        // 5 tags exist; the 4th visible is "silver robe" and the 5th is folded
        // into the overflow marker.
        expect(screen.getByText('elf')).toBeInTheDocument();
        expect(screen.getByText('silver robe')).toBeInTheDocument();
        expect(screen.queryByText('moonlit')).not.toBeInTheDocument();
        expect(screen.getByText('+1')).toBeInTheDocument();
    });

    it('browse mode offers chat and view, and no management actions', () => {
        const onChat = vi.fn();
        const onOpen = vi.fn();
        render(<CharacterCard character={character} onChat={onChat} onOpen={onOpen} />);

        expect(screen.getByTitle('Start chat with this character')).toBeInTheDocument();
        expect(screen.getByTitle('Open character')).toBeInTheDocument();
        expect(screen.queryByTitle('Edit character')).not.toBeInTheDocument();
        expect(screen.queryByTitle('Delete character')).not.toBeInTheDocument();
        expect(screen.queryByTitle('Clone character')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Reorder Elara Moonwhisper' })).not.toBeInTheDocument();

        fireEvent.click(screen.getByTitle('Start chat with this character'));
        expect(onChat).toHaveBeenCalledWith(character);

        fireEvent.click(screen.getByTitle('Open character'));
        expect(onOpen).toHaveBeenCalledWith(character);
    });

    it('management mode renders every provided action and passes the character', () => {
        const onEdit = vi.fn();
        const onDelete = vi.fn();
        const onClone = vi.fn();
        const onExport = vi.fn();
        render(
            <CharacterCard
                character={character}
                onChat={() => {}}
                actions={{ onEdit, onDelete, onClone, onExport }}
            />
        );

        expect(screen.queryByTitle('Open character')).not.toBeInTheDocument();

        fireEvent.click(screen.getByTitle('Edit character'));
        expect(onEdit).toHaveBeenCalledWith(character);

        fireEvent.click(screen.getByTitle('Clone character'));
        expect(onClone).toHaveBeenCalledWith(character);

        fireEvent.click(screen.getByTitle('Delete character'));
        expect(onDelete).toHaveBeenCalledWith(character);

        fireEvent.click(screen.getByRole('button', { name: 'Export card for Elara Moonwhisper' }));
        fireEvent.click(screen.getByRole('menuitem', { name: /V2 PNG/ }));
        expect(onExport).toHaveBeenCalledWith(character, 'v2');
    });

    it('disables only the clone button while that character is being cloned', () => {
        render(
            <CharacterCard
                character={character}
                onChat={() => {}}
                actions={{ onClone: vi.fn(), isCloning: true }}
            />
        );

        expect(screen.getByTitle('Clone character')).toBeDisabled();
        expect(screen.getByTitle('Start chat with this character')).not.toBeDisabled();
    });

    it('SortableCharacterCard adds the reorder handle and dnd wiring', () => {
        renderInDnd(<SortableCharacterCard character={character} onChat={() => {}} />);

        const handle = screen.getByRole('button', { name: 'Reorder Elara Moonwhisper' });
        expect(handle).toBeInTheDocument();
        // dnd-kit's activator attributes, so the handle is actually draggable.
        expect(handle).toHaveAttribute('aria-roledescription');
        expect(handle).toHaveAttribute('tabindex');
    });
});
