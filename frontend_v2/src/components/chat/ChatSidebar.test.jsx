import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ChatSidebar from './ChatSidebar';

function renderSidebar(overrides = {}) {
    const props = {
        chatsCollapsed: false,
        mobileTab: 'chats',
        handleCreateChat: vi.fn(),
        chatSearchQuery: '',
        setChatSearchQuery: vi.fn(),
        setChatOffset: vi.fn(),
        isChatsLoading: false,
        chats: [],
        activeChatList: [],
        renamingChatId: null,
        renameValue: '',
        setRenameValue: vi.fn(),
        finishRename: vi.fn(),
        setActiveChatId: vi.fn(),
        setMobileTab: vi.fn(),
        activeChatId: null,
        characters: [],
        startRename: vi.fn(),
        handleDeleteChat: vi.fn(),
        handleImportChatFile: vi.fn(),
        isImportingChat: false,
        hasMoreChats: false,
        CHAT_PAGE_SIZE: 50,
        setRenamingChatId: vi.fn(),
        ...overrides,
    };
    return render(<ChatSidebar {...props} />);
}

describe('ChatSidebar import control', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('renders an import button next to New chat', () => {
        renderSidebar();
        expect(screen.getByTitle(/Import chat/)).toBeInTheDocument();
        expect(screen.getByTitle('New chat')).toBeInTheDocument();
    });

    it('shows a spinner while importing', () => {
        renderSidebar({ isImportingChat: true });
        const btn = screen.getByTitle(/Import chat/);
        expect(btn).toBeDisabled();
        expect(btn.querySelector('.animate-spin')).toBeInTheDocument();
    });

    it('passes the picked file to handleImportChatFile and resets the input', () => {
        const handleImportChatFile = vi.fn();
        renderSidebar({ handleImportChatFile });
        const input = document.querySelector('input[type="file"]');
        expect(input).not.toBeNull();
        expect(input.accept).toContain('.jsonl');
        const file = new File(['{"user_name":"U"}'], 'chat.jsonl', { type: 'application/x-ndjson' });
        fireEvent.change(input, { target: { files: [file] } });
        expect(handleImportChatFile).toHaveBeenCalledTimes(1);
        expect(handleImportChatFile.mock.calls[0][0]).toBe(file);
        expect(input.value).toBe('');
    });

    it('ignores empty file selections', () => {
        const handleImportChatFile = vi.fn();
        renderSidebar({ handleImportChatFile });
        const input = document.querySelector('input[type="file"]');
        fireEvent.change(input, { target: { files: [] } });
        expect(handleImportChatFile).not.toHaveBeenCalled();
    });
});
