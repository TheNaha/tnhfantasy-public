import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Characters from './Characters';

vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual('react-router-dom');
    return { ...actual, useNavigate: () => vi.fn() };
});

const mockUseCharacters = vi.hoisted(() => vi.fn());
const mockCreateCharacter = vi.hoisted(() => vi.fn());
const mockUpdateCharacter = vi.hoisted(() => vi.fn());
const mockDeleteCharacter = vi.hoisted(() => vi.fn());
const mockImportCharacterCard = vi.hoisted(() => vi.fn());
const mockExportCharacterCard = vi.hoisted(() => vi.fn());
const mockSetActiveChat = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useVoices', () => ({
    useVoices: () => ({ data: [] }),
}));

vi.mock('../hooks/useWorldVault', () => ({
    useCharacters: (...args) => mockUseCharacters(...args),
    useCreateCharacter: () => mockCreateCharacter(),
    useUpdateCharacter: () => mockUpdateCharacter(),
    useDeleteCharacter: () => mockDeleteCharacter(),
    useUploadAvatar: () => ({ mutateAsync: vi.fn() }),
    useCharacterCollection: () => ({ data: null }),
    useCharacterCollections: () => ({ data: {} }),
    useImportCharacterCard: () => mockImportCharacterCard(),
    useExportCharacterCard: () => mockExportCharacterCard(),
    useReorderCharacters: () => ({ mutate: vi.fn(), isPending: false }),
    useAnimateCharacterAvatar: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useCloneCharacter: () => ({ mutateAsync: vi.fn(), isPending: false }),
    getAvatarUrl: () => '',
}));

vi.mock('../store/worldVaultStore', () => ({
    useWorldVaultStore: (sel) => sel({ setActiveChat: mockSetActiveChat }),
}));

vi.mock('../components/EmptyState', () => ({
    default: ({ title }) => <div data-testid="empty-state">{title}</div>,
}));

vi.mock('../components/ConfirmationModal', () => ({
    default: ({ isOpen, onConfirm, title }) =>
        isOpen ? (
            <div data-testid="confirm-modal">
                <span>{title}</span>
                <button onClick={onConfirm}>Confirm</button>
            </div>
        ) : null,
}));

function buildCharacter(overrides = {}) {
    return {
        id: 'char-1',
        name: 'Alice',
        description: 'A friendly girl',
        personality: 'Cheerful and kind',
        scenario: 'Fantasy world',
        first_mes: 'Hello!',
        mes_example: '',
        system_prompt: '',
        visual_tags: ['1girl', 'blonde'],
        lora_triggers: [],
        has_avatar: false,
        ...overrides,
    };
}

describe('Characters page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockUseCharacters.mockReturnValue({ data: [buildCharacter()], isLoading: false });
        mockCreateCharacter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ id: 'new-1' }) });
        mockUpdateCharacter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockDeleteCharacter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockImportCharacterCard.mockReturnValue({
            mutateAsync: vi.fn().mockResolvedValue({
                character: { id: 'imported-1', name: 'Imported' },
                compatibility: {
                    format: 'v2',
                    spec: 'chara_card_v2.0',
                    specVersion: '2.0',
                    warnings: [],
                    lost: [],
                    preserved: [],
                    lorebookConverted: null,
                    unknownExtensionsPreserved: null,
                    hasReport: true,
                    lossless: true,
                },
            }),
            isPending: false,
        });
        mockExportCharacterCard.mockReturnValue({
            mutateAsync: vi
                .fn()
                .mockResolvedValue({ url: '/api/v2/characters/char-1/export', filename: 'Alice_v2.png' }),
            isPending: false,
        });
    });

    it('renders the page heading', () => {
        render(<Characters />, { wrapper: MemoryRouter });
        expect(screen.getByText('Character Vault')).toBeInTheDocument();
    });

    it('displays character cards with name and description', () => {
        render(<Characters />, { wrapper: MemoryRouter });
        expect(screen.getByText('Alice')).toBeInTheDocument();
        expect(screen.getByText('A friendly girl')).toBeInTheDocument();
    });

    it('shows visual tags on character cards', () => {
        render(<Characters />, { wrapper: MemoryRouter });
        expect(screen.getByText('1girl')).toBeInTheDocument();
        expect(screen.getByText('blonde')).toBeInTheDocument();
    });

    it('displays character count', () => {
        render(<Characters />, { wrapper: MemoryRouter });
        expect(screen.getByText('1 character')).toBeInTheDocument();
    });

    it('filters characters by search query', () => {
        render(<Characters />, { wrapper: MemoryRouter });
        const searchInput = screen.getByPlaceholderText(/Search characters/);
        fireEvent.change(searchInput, { target: { value: 'Alice' } });
        expect(screen.getByText('Alice')).toBeInTheDocument();

        fireEvent.change(searchInput, { target: { value: 'zzz' } });
        expect(screen.getByText('No Characters Match')).toBeInTheDocument();
    });

    it('shows empty state when no characters exist', () => {
        mockUseCharacters.mockReturnValue({ data: [], isLoading: false });
        render(<Characters />, { wrapper: MemoryRouter });
        expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    });

    it('shows loading spinner while fetching', () => {
        mockUseCharacters.mockReturnValue({ data: [], isLoading: true });
        const { container } = render(<Characters />, { wrapper: MemoryRouter });
        expect(container.querySelector('.animate-spin')).toBeInTheDocument();
    });

    it('opens create modal when Create Character is clicked', async () => {
        render(<Characters />, { wrapper: MemoryRouter });
        fireEvent.click(screen.getByText('Create Character'));
        await waitFor(() => {
            expect(screen.getByText('Create Character', { selector: 'h2' })).toBeInTheDocument();
        });
    });

    it('shows character personality in italics', () => {
        render(<Characters />, { wrapper: MemoryRouter });
        expect(screen.getByText(/Cheerful and kind/)).toBeInTheDocument();
    });

    it('accepts both PNG and JSON card files', () => {
        const { container } = render(<Characters />, { wrapper: MemoryRouter });
        const input = container.querySelector('input[type="file"]');
        expect(input.accept).toContain('.png');
        expect(input.accept).toContain('.json');
    });

    it('shows the compatibility report after importing a card', async () => {
        const mutateAsync = vi.fn().mockResolvedValue({
            character: { id: 'imported-1', name: 'Sable' },
            compatibility: {
                format: 'json',
                spec: 'chara_card_v3',
                specVersion: '3.0',
                warnings: [{ id: 'tags', label: 'Tags mapped to visual tags', detail: '' }],
                lost: [{ id: 'regex_scripts', label: 'regex_scripts', detail: 'no matching feature' }],
                preserved: [{ id: 'card_metadata', label: 'card_metadata', detail: '' }],
                lorebookConverted: true,
                unknownExtensionsPreserved: null,
                hasReport: true,
                lossless: false,
            },
        });
        mockImportCharacterCard.mockReturnValue({ mutateAsync, isPending: false });

        const { container } = render(<Characters />, { wrapper: MemoryRouter });
        const input = container.querySelector('input[type="file"]');
        const file = new File(['{}'], 'sable.json', { type: 'application/json' });
        fireEvent.change(input, { target: { files: [file] } });

        await waitFor(() => expect(screen.getByTestId('card-import-report-overlay')).toBeInTheDocument());
        expect(mutateAsync).toHaveBeenCalledWith(file);
        expect(screen.getByText('Sable')).toBeInTheDocument();
        expect(screen.getByTestId('card-import-status')).toHaveTextContent(/Imported with warnings/i);
        expect(screen.getByTestId('card-import-warnings')).toHaveTextContent('Tags mapped to visual tags');
        expect(screen.getByTestId('card-import-lost')).toHaveTextContent('regex_scripts');
        expect(screen.getByTestId('card-import-preserved')).toHaveTextContent('card_metadata');
        expect(screen.getByTestId('card-import-lorebook')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: 'Close' }));
        expect(screen.queryByTestId('card-import-report-overlay')).not.toBeInTheDocument();
    });

    it('surfaces import failures without opening the report', async () => {
        mockImportCharacterCard.mockReturnValue({
            mutateAsync: vi.fn().mockRejectedValue({ data: { detail: 'Only PNG files are supported' } }),
            isPending: false,
        });

        const { container } = render(<Characters />, { wrapper: MemoryRouter });
        const input = container.querySelector('input[type="file"]');
        fireEvent.change(input, {
            target: { files: [new File(['{}'], 'card.json', { type: 'application/json' })] },
        });

        await waitFor(() => expect(screen.queryByTestId('card-import-report-overlay')).not.toBeInTheDocument());
    });

    it('exports a character card in the chosen format', async () => {
        const mutateAsync = vi.fn().mockResolvedValue({ url: '/x', filename: 'Alice_v3.png' });
        mockExportCharacterCard.mockReturnValue({ mutateAsync, isPending: false });

        render(<Characters />, { wrapper: MemoryRouter });
        fireEvent.click(screen.getByRole('button', { name: /export card for alice/i }));
        fireEvent.click(screen.getByRole('menuitem', { name: /V3 PNG/ }));

        await waitFor(() =>
            expect(mutateAsync).toHaveBeenCalledWith({ character: expect.objectContaining({ id: 'char-1' }), format: 'v3' })
        );
    });

    it('keeps the default export path free of a format param', async () => {
        const mutateAsync = vi.fn().mockResolvedValue({ url: '/x', filename: 'Alice_v2.png' });
        mockExportCharacterCard.mockReturnValue({ mutateAsync, isPending: false });

        render(<Characters />, { wrapper: MemoryRouter });
        fireEvent.click(screen.getByRole('button', { name: /export card for alice/i }));
        fireEvent.click(screen.getByRole('menuitem', { name: /V2 PNG/ }));

        await waitFor(() =>
            expect(mutateAsync).toHaveBeenCalledWith({ character: expect.objectContaining({ id: 'char-1' }), format: 'v2' })
        );
    });

    it('shows card provenance and preserved metadata on imported cards', () => {
        mockUseCharacters.mockReturnValue({
            data: [
                buildCharacter({
                    card_spec: 'chara_card_v2',
                    card_spec_version: '2.0',
                    card_metadata: { data: { extensions: { tavern_helper: {} } } },
                }),
            ],
            isLoading: false,
        });
        render(<Characters />, { wrapper: MemoryRouter });

        const badge = screen.getByTestId('card-spec-badge');
        expect(badge).toHaveTextContent('V2 · 2.0 card');
        expect(badge).toHaveTextContent('1 metadata group');
    });

    it('keeps the drag handle, chat and edit actions', () => {
        render(<Characters />, { wrapper: MemoryRouter });

        expect(screen.getByRole('button', { name: 'Reorder Alice' })).toBeInTheDocument();
        expect(screen.getByTitle('Start chat with this character')).toBeInTheDocument();
        expect(screen.getByTitle('Edit character')).toBeInTheDocument();
        expect(screen.getByTitle('Clone character')).toBeInTheDocument();
    });
});
