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
    useImportCharacterCard: () => mockImportCharacterCard(),
    useAnimateCharacterAvatar: () => ({ mutateAsync: vi.fn(), isPending: false }),
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
        mockImportCharacterCard.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ name: 'Imported' }), isPending: false });
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
});
