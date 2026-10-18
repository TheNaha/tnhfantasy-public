import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CompanionPickerModal from './CompanionPickerModal';

describe('CompanionPickerModal', () => {
    const mockCharacters = [
        { id: 'c-1', name: 'Aria', tagline: 'A gentle scholar' },
        { id: 'c-2', name: 'Kael', tagline: 'A rogue scout' },
        { id: 'c-3', name: 'Lyra', tagline: 'A mystic mage' },
    ];

    it('renders primary character as non-removable and companions selected', () => {
        render(
            <CompanionPickerModal
                isOpen
                onClose={() => {}}
                characters={mockCharacters}
                primaryCharacterId="c-1"
                additionalCharacterIds={['c-2']}
                onSave={() => {}}
            />
        );

        expect(screen.getByText('Group Chat Companions')).toBeInTheDocument();
        expect(screen.getByText('Primary')).toBeInTheDocument();
        expect(screen.getByText('1 companion selected')).toBeInTheDocument();
    });

    it('filters characters based on search query', () => {
        render(
            <CompanionPickerModal
                isOpen
                onClose={() => {}}
                characters={mockCharacters}
                primaryCharacterId="c-1"
                additionalCharacterIds={[]}
                onSave={() => {}}
            />
        );

        const input = screen.getByPlaceholderText(/search characters/i);
        fireEvent.change(input, { target: { value: 'rogue' } });

        expect(screen.getByText('Kael')).toBeInTheDocument();
        expect(screen.queryByText('Lyra')).not.toBeInTheDocument();
    });

    it('toggles companion selection and calls onSave with updated IDs', () => {
        const onSave = vi.fn();
        const onClose = vi.fn();

        render(
            <CompanionPickerModal
                isOpen
                onClose={onClose}
                characters={mockCharacters}
                primaryCharacterId="c-1"
                additionalCharacterIds={['c-2']}
                onSave={onSave}
            />
        );

        // Click Lyra to add to party
        fireEvent.click(screen.getByText('Lyra'));
        expect(screen.getByText('2 companions selected')).toBeInTheDocument();

        // Submit
        fireEvent.click(screen.getByRole('button', { name: /update party/i }));
        expect(onSave).toHaveBeenCalledWith(['c-2', 'c-3']);
        expect(onClose).toHaveBeenCalled();
    });
});
