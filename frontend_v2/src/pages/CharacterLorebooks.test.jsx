/**
 * The character ↔ lorebook link, from the modal's side.
 *
 * The column existed without a control: `Character.lorebook_ids` could not be
 * set anywhere in the product, so a Lorebooks page that promises "character
 * backgrounds" was promising nothing. These tests pin the control, the
 * read-only treatment of the card's embedded book (a DIFFERENT relationship
 * that looks identical from the outside), and the payload the save path sends.
 */
import { useState } from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { CharacterModal } from './Characters';

vi.mock('../hooks/useVoices', () => ({ useVoices: () => ({ data: [] }) }));
vi.mock('../hooks/useLLMJobResult', () => ({ useLLMJobResult: () => ({ reset: vi.fn() }) }));

const mockUseLorebooks = vi.hoisted(() => vi.fn());
const mockUploadAvatar = vi.hoisted(() => vi.fn());
const mockAnimateAvatar = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useWorldVault', () => ({
    useUploadAvatar: () => ({ mutateAsync: mockUploadAvatar, isPending: false }),
    useAnimateCharacterAvatar: () => ({ mutateAsync: mockAnimateAvatar, isPending: false }),
    useUpdateCharacter: () => ({ mutateAsync: vi.fn() }),
    useCreateCharacter: () => ({ mutateAsync: vi.fn() }),
    useLorebooks: () => mockUseLorebooks(),
    useWorlds: () => ({ data: [] }),
}));
vi.mock('../components/chat/MemoriesPanel', () => ({
    default: () => <div data-testid="memories-panel">memories</div>,
}));

const LOREBOOKS = [
    { id: 'lb-ashfall', name: 'Ashfall Codex' },
    { id: 'lb-river', name: 'Riverlands' },
    { id: 'lb-cards', name: 'The Card Author’s Own Notes' },
    { id: 'lb-drowned', name: 'Drowned Road' },
    { id: 'lb-salt', name: 'Saltmarsh' },
    { id: 'lb-tide', name: 'Tidewrack' },
    { id: 'lb-kelp', name: 'Kelp Forests' },
];

function makeCharacter(overrides = {}) {
    return {
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
        lorebook_ids: [],
        ...overrides,
    };
}

function renderModal({ character = makeCharacter(), onSave = vi.fn() } = {}) {
    render(
        <MemoryRouter>
            <CharacterModal isOpen onClose={() => {}} character={character} onSave={onSave} />
        </MemoryRouter>
    );
    return { onSave };
}

describe('CharacterModal lorebook picker', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockUseLorebooks.mockReturnValue({ data: LOREBOOKS });
    });

    it('lists the vault lorebooks with none attached by default', () => {
        renderModal();

        expect(screen.getByTestId('character-lorebooks')).toBeInTheDocument();
        expect(screen.getByLabelText('Attach Ashfall Codex')).not.toBeChecked();
        expect(screen.getByLabelText('Attach Riverlands')).not.toBeChecked();
        expect(screen.queryByTestId('character-lorebooks-count')).not.toBeInTheDocument();
    });

    it('shows which books are already attached', () => {
        renderModal({ character: makeCharacter({ lorebook_ids: ['lb-river'] }) });

        expect(screen.getByLabelText('Attach Riverlands')).toBeChecked();
        expect(screen.getByLabelText('Attach Ashfall Codex')).not.toBeChecked();
        expect(screen.getByTestId('character-lorebooks-count')).toHaveTextContent('1 lorebook attached');
    });

    it('sends the attached ids on save, in the order they were picked', async () => {
        const onSave = vi.fn().mockResolvedValue({ id: 'char-1' });
        renderModal({ onSave });

        fireEvent.click(screen.getByLabelText('Attach Riverlands'));
        fireEvent.click(screen.getByLabelText('Attach Ashfall Codex'));
        expect(screen.getByTestId('character-lorebooks-count')).toHaveTextContent('2 lorebooks attached');

        fireEvent.change(screen.getByLabelText('Search lorebooks'), { target: { value: '' } });
        fireEvent.click(screen.getByRole('button', { name: 'Update' }));

        await vi.waitFor(() => expect(onSave).toHaveBeenCalled());
        expect(onSave.mock.calls[0][0].lorebook_ids).toEqual(['lb-river', 'lb-ashfall']);
    });

    it('detaches by unticking, and an empty list is sent rather than omitted', async () => {
        const onSave = vi.fn().mockResolvedValue({ id: 'char-1' });
        renderModal({
            character: makeCharacter({ lorebook_ids: ['lb-river', 'lb-ashfall'] }),
            onSave,
        });

        fireEvent.click(screen.getByLabelText('Attach Riverlands'));
        expect(screen.getByTestId('character-lorebooks-count')).toHaveTextContent('1 lorebook attached');

        fireEvent.click(screen.getByRole('button', { name: 'Update' }));
        await vi.waitFor(() => expect(onSave).toHaveBeenCalled());
        // The key that must be sent: `[]` clears, and dropping the key would
        // leave the old books attached with no way back from the UI.
        expect(onSave.mock.calls[0][0].lorebook_ids).toEqual(['lb-ashfall']);
    });

    it('filters with a search box once the vault is not a handful of books', () => {
        renderModal();

        const search = screen.getByLabelText('Search lorebooks');
        fireEvent.change(search, { target: { value: 'river' } });

        expect(screen.getByLabelText('Attach Riverlands')).toBeInTheDocument();
        expect(screen.queryByLabelText('Attach Saltmarsh')).not.toBeInTheDocument();
    });

    it('does not show a search box for a small vault', () => {
        mockUseLorebooks.mockReturnValue({ data: LOREBOOKS.slice(0, 6) });
        renderModal();
        expect(screen.queryByLabelText('Search lorebooks')).not.toBeInTheDocument();
    });

    it('keeps an attached book visible while the search hides it, so it can be unticked', () => {
        renderModal({ character: makeCharacter({ lorebook_ids: ['lb-river'] }) });

        fireEvent.change(screen.getByLabelText('Search lorebooks'), { target: { value: 'salt' } });

        expect(screen.getByLabelText('Attach Riverlands')).toBeChecked();
        expect(screen.queryByLabelText('Attach Saltmarsh')).toBeInTheDocument();
    });

    it('says so when the vault has no books at all', () => {
        mockUseLorebooks.mockReturnValue({ data: [] });
        renderModal();

        expect(screen.getByTestId('character-lorebooks-empty')).toBeInTheDocument();
        expect(screen.getByText(/every chat and story/i)).toBeInTheDocument();
    });

    // ── the embedded card book is a different relationship ────────────────

    it('shows the embedded card lorebook as a read-only, separately-labelled row', () => {
        renderModal({
            character: makeCharacter({ embedded_lorebook_id: 'lb-cards' }),
        });

        const row = screen.getByTestId('character-embedded-lorebook');
        expect(row).toHaveTextContent('The Card Author’s Own Notes');
        expect(row).toHaveTextContent(/belongs to the imported card/i);
    });

    it('does not also offer the embedded book as something to attach', () => {
        // The same book rendered twice — once untouchable, once a checkbox —
        // is the confusion the row exists to prevent, and it is already
        // injected into every chat with this character anyway.
        renderModal({ character: makeCharacter({ embedded_lorebook_id: 'lb-cards' }) });

        expect(screen.queryByLabelText('Attach The Card Author’s Own Notes')).not.toBeInTheDocument();
        expect(screen.getByLabelText('Attach Ashfall Codex')).toBeInTheDocument();
    });

    it('omits the embedded row for a character that has no card book', () => {
        renderModal();
        expect(screen.queryByTestId('character-embedded-lorebook')).not.toBeInTheDocument();
    });

    it('never sends the embedded id as an attached one', async () => {
        const onSave = vi.fn().mockResolvedValue({ id: 'char-1' });
        renderModal({ character: makeCharacter({ embedded_lorebook_id: 'lb-cards' }), onSave });

        fireEvent.click(screen.getByRole('button', { name: 'Update' }));

        await vi.waitFor(() => expect(onSave).toHaveBeenCalled());
        const payload = onSave.mock.calls[0][0];
        expect(payload.lorebook_ids).toEqual([]);
        expect(payload.embedded_lorebook_id).toBeUndefined();
    });

    it('surfaces an attached book that no longer exists so it can be dropped', () => {
        mockUseLorebooks.mockReturnValue({ data: [LOREBOOKS[0], LOREBOOKS[1]] });
        renderModal({ character: makeCharacter({ lorebook_ids: ['lb-gone'] }) });

        expect(screen.getByLabelText('Detach missing lorebook lb-gone')).toBeChecked();
        expect(screen.getByText(/missing — untick to drop/i)).toBeInTheDocument();
    });

    it('works when the character record predates the field entirely', () => {
        const legacy = makeCharacter();
        delete legacy.lorebook_ids;
        renderModal({ character: legacy });

        expect(screen.getByLabelText('Attach Ashfall Codex')).not.toBeChecked();
        expect(screen.queryByTestId('character-lorebooks-count')).not.toBeInTheDocument();
    });
});

describe('CharacterModal lorebook picker in a controlled parent', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockUseLorebooks.mockReturnValue({ data: LOREBOOKS });
    });

    it('does not need an onTabChange, like the StorySandbox call site', () => {
        const Wrapper = () => {
            const [tab, setTab] = useState('details');
            return (
                <MemoryRouter>
                    <CharacterModal
                        isOpen
                        onClose={() => {}}
                        character={makeCharacter({ lorebook_ids: ['lb-ashfall'] })}
                        onSave={() => {}}
                        activeTab={tab}
                        onTabChange={setTab}
                    />
                </MemoryRouter>
            );
        };
        render(<Wrapper />);

        expect(screen.getByLabelText('Attach Ashfall Codex')).toBeChecked();
    });
});
