/**
 * CharacterModal tab-bar regression test.
 *
 * StorySandbox renders CharacterModal from the story context panel passing only
 * isOpen/onClose/character/onSave. `onTabChange` therefore arrives undefined,
 * and the unguarded `onTabChange('memories')` in the tab bar threw
 * `TypeError: onTabChange is not a function` on the first click.
 */
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { CharacterModal } from './Characters';

vi.mock('../hooks/useVoices', () => ({ useVoices: () => ({ data: [] }) }));
vi.mock('../hooks/useLLMJobResult', () => ({ useLLMJobResult: () => ({ reset: vi.fn() }) }));
vi.mock('../hooks/useWorldVault', () => ({
    useUploadAvatar: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useAnimateCharacterAvatar: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useUpdateCharacter: () => ({ mutateAsync: vi.fn() }),
    useCreateCharacter: () => ({ mutateAsync: vi.fn() }),
}));
vi.mock('../components/chat/MemoriesPanel', () => ({
    default: () => <div data-testid="memories-panel">memories</div>,
}));

const character = {
    id: 'char-1',
    name: 'Alice',
    description: '',
    personality: '',
    scenario: '',
    first_mes: '',
    mes_example: '',
    system_prompt: '',
    visual_tags: [],
    lora_triggers: [],
};

describe('CharacterModal tab bar', () => {
    it('switches tabs when mounted without onTabChange (StorySandbox call site)', () => {
        render(
            <MemoryRouter>
                <CharacterModal
                    isOpen
                    onClose={() => {}}
                    character={character}
                    onSave={() => {}}
                />
            </MemoryRouter>
        );

        expect(screen.queryByTestId('memories-panel')).not.toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: /memories/i }));
        expect(screen.getByTestId('memories-panel')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: /^details$/i }));
        expect(screen.queryByTestId('memories-panel')).not.toBeInTheDocument();
    });

    it('still reports tab changes to a controlled parent', () => {
        const onTabChange = vi.fn();
        const Wrapper = () => {
            const [tab, setTab] = useState('details');
            return (
                <MemoryRouter>
                    <CharacterModal
                        isOpen
                        onClose={() => {}}
                        character={character}
                        onSave={() => {}}
                        activeTab={tab}
                        onTabChange={(next) => { setTab(next); onTabChange(next); }}
                    />
                </MemoryRouter>
            );
        };
        render(<Wrapper />);

        fireEvent.click(screen.getByRole('button', { name: /memories/i }));
        expect(onTabChange).toHaveBeenCalledWith('memories');
        expect(screen.getByTestId('memories-panel')).toBeInTheDocument();
    });
});
