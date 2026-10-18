import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import ChatInputContainer from './ChatInputContainer';

vi.mock('../../hooks/useCharacters', () => ({
    useCharacters: () => ({ data: [] }),
}));

vi.mock('../../hooks/useLorebooks', () => ({
    useLorebooks: () => ({ data: [] }),
}));

describe('ChatInputContainer', () => {
    let queryClient;

    beforeEach(() => {
        queryClient = new QueryClient({
            defaultOptions: { queries: { retry: false } },
        });
    });

    const renderWithClient = (ui) => {
        return render(
            <QueryClientProvider client={queryClient}>
                {ui}
            </QueryClientProvider>
        );
    };

    const defaultProps = {
        pendingAttachment: null,
        setPendingAttachment: vi.fn(),
        activeChat: {
            id: 'chat-1',
            name: 'Test Chat',
            state_snapshot: {
                location: 'Grand Ballroom',
                mood: 'Amused',
            },
        },
        targetCharacterId: '',
        setTargetCharacterId: vi.fn(),
        characters: [],
        message: '',
        activeCommand: null,
        setActiveCommand: vi.fn(),
        setMessage: vi.fn(),
        handleSuggestClick: vi.fn(),
        fileInputRef: { current: null },
        handleAttachmentChange: vi.fn(),
        textareaRef: { current: null },
        handleTextChange: vi.fn(),
        handleKeyDown: vi.fn(),
        activeChatId: 'chat-1',
        sendMessageMutation: { isPending: false },
        isUploading: false,
        showMoreTools: false,
        setShowMoreTools: vi.fn(),
        handleGenerateScene: vi.fn(),
        isGeneratingScene: false,
        handleIllustrate: vi.fn(),
        illustrateMutation: { isPending: false },
        agenticMode: false,
        setAgenticMode: vi.fn(),
        narrateMode: false,
        setNarrateMode: vi.fn(),
        handleImpersonate: vi.fn(),
        impersonateMutation: { isPending: false },
        suggestReplyMutation: { isPending: false },
        suggestJobId: null,
        handleSendMessage: vi.fn(),
        canSend: true,
        isGeneratingReply: false,
        handleCancelStreaming: vi.fn(),
        turnDirective: '',
        setTurnDirective: vi.fn(),
    };

    it('renders clean input bar with quick auto-suggest and tools menu trigger', () => {
        renderWithClient(<ChatInputContainer {...defaultProps} />);

        expect(screen.getByTitle('Attach image')).toBeInTheDocument();
        expect(screen.getByTitle('Auto-suggest reply')).toBeInTheDocument();
        expect(screen.getByTitle('Story & Roleplay Tools')).toBeInTheDocument();
        expect(screen.getByLabelText('Send message')).toBeInTheDocument();
    });

    it('toggles the Story & Roleplay Tools menu on click', () => {
        const setShowMoreTools = vi.fn();
        renderWithClient(<ChatInputContainer {...defaultProps} setShowMoreTools={setShowMoreTools} />);

        const toolsBtn = screen.getByTitle('Story & Roleplay Tools');
        fireEvent.click(toolsBtn);
        expect(setShowMoreTools).toHaveBeenCalledWith(expect.any(Function));
    });

    it('renders categorized popover when showMoreTools is true', () => {
        renderWithClient(<ChatInputContainer {...defaultProps} showMoreTools={true} />);

        // Sections
        expect(screen.getByText('Visuals & Media')).toBeInTheDocument();
        expect(screen.getByText('Director & Mechanics')).toBeInTheDocument();
        expect(screen.getByText('Player Co-Pilot')).toBeInTheDocument();
        expect(screen.getByText('Engine Modes')).toBeInTheDocument();

        // Items
        expect(screen.getByText('Scene')).toBeInTheDocument();
        expect(screen.getByText('Illustrate')).toBeInTheDocument();
        expect(screen.getByText('Steer Turn')).toBeInTheDocument();
        expect(screen.getByText('Fate / D20')).toBeInTheDocument();
        expect(screen.getByText('Suggest')).toBeInTheDocument();
        expect(screen.getByText('Impersonate')).toBeInTheDocument();
        expect(screen.getByText('Autonomous Agentic')).toBeInTheDocument();
        expect(screen.getByText('Scene Narrator')).toBeInTheDocument();
    });

    it('triggers generate scene and closes menu on click', () => {
        const handleGenerateScene = vi.fn();
        const setShowMoreTools = vi.fn();
        renderWithClient(
            <ChatInputContainer
                {...defaultProps}
                showMoreTools={true}
                handleGenerateScene={handleGenerateScene}
                setShowMoreTools={setShowMoreTools}
            />
        );

        fireEvent.click(screen.getByText('Scene'));
        expect(setShowMoreTools).toHaveBeenCalledWith(false);
        expect(handleGenerateScene).toHaveBeenCalled();
    });

    it('triggers illustrate and closes menu on click', () => {
        const handleIllustrate = vi.fn();
        const setShowMoreTools = vi.fn();
        renderWithClient(
            <ChatInputContainer
                {...defaultProps}
                showMoreTools={true}
                handleIllustrate={handleIllustrate}
                setShowMoreTools={setShowMoreTools}
            />
        );

        fireEvent.click(screen.getByText('Illustrate'));
        expect(setShowMoreTools).toHaveBeenCalledWith(false);
        expect(handleIllustrate).toHaveBeenCalled();
    });

    it('toggles agentic mode on click', () => {
        const setAgenticMode = vi.fn();
        renderWithClient(
            <ChatInputContainer
                {...defaultProps}
                showMoreTools={true}
                agenticMode={false}
                setAgenticMode={setAgenticMode}
            />
        );

        fireEvent.click(screen.getByText('Autonomous Agentic'));
        expect(setAgenticMode).toHaveBeenCalledWith(true);
    });

    it('toggles narrate mode on click', () => {
        const setNarrateMode = vi.fn();
        renderWithClient(
            <ChatInputContainer
                {...defaultProps}
                showMoreTools={true}
                narrateMode={false}
                setNarrateMode={setNarrateMode}
            />
        );

        fireEvent.click(screen.getByText('Scene Narrator'));
        expect(setNarrateMode).toHaveBeenCalledWith(true);
    });

    it('dismisses popover on Escape key press', () => {
        const setShowMoreTools = vi.fn();
        renderWithClient(<ChatInputContainer {...defaultProps} showMoreTools={true} setShowMoreTools={setShowMoreTools} />);

        fireEvent.keyDown(window, { key: 'Escape' });
        expect(setShowMoreTools).toHaveBeenCalledWith(false);
    });
});
