import React from 'react';
import { cleanup, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * `useChatWorkspaceData` is the single read-side choke point for the chat
 * workspace, and it discarded `isError` on all 16 of its queries.
 *
 * Each one destructured `data` with a `= []` default, so a rejected request
 * produced the same value as a genuinely empty result — and every consumer
 * built its emptiness copy on that: "No chats yet", "No lorebooks available",
 * "No locations". `rg "isError|QueryErrorState|QueryGate"` across the hook and
 * its consumers returned zero hits, which is the signature of a fix made once
 * in the wrong place and then not at all.
 *
 * The consumers are handed arrays and a context, so they cannot reach a query
 * object themselves. The error state has to be surfaced HERE or nowhere.
 */

const queryState = vi.hoisted(() => ({ current: {} }));

/** Every hook the choke point calls, so the test controls each one's failure. */
const FAILABLE = [
    'useChats', 'useSearchChats', 'useMessages', 'useChat', 'useLorebooks',
    'useCharacters', 'usePersonas', 'useLLMAvailableModels', 'useLLMDefaultProvider',
    'useChatSystemPrompt', 'useCharacterCollection', 'useChatImages',
    'useChatJobs', 'useWorlds',
];

// `vi.hoisted`, not a plain loop: `vi.mock` is hoisted above module
// initialisation, so a factory referencing a normal `const` throws
// "Cannot access before initialization" before a single test runs.
const worldVaultMock = vi.hoisted(() => {
    const names = [
        'useChats', 'useSearchChats', 'useMessages', 'useChat', 'useLorebooks',
        'useCharacters', 'usePersonas', 'useLLMAvailableModels', 'useLLMDefaultProvider',
        'useChatSystemPrompt', 'useCharacterCollection', 'useChatImages',
        'useChatJobs', 'useWorlds',
    ];
    const mocks = {};
    for (const name of names) {
        mocks[name] = vi.fn(() => ({ data: [], isError: false, error: null, refetch: vi.fn() }));
    }
    return mocks;
});

vi.mock('../hooks/useWorldVault', () => worldVaultMock);
vi.mock('../hooks/useVoices', () => ({
    useVoices: vi.fn(() => ({ data: [], isError: false, error: null, refetch: vi.fn() })),
}));
vi.mock('../hooks/useCollections', () => ({
    useCollections: vi.fn(() => ({ data: {}, isError: false, error: null, refetch: vi.fn() })),
}));
vi.mock('../hooks/useStreamingJobs', () => ({ useActiveChatStreams: vi.fn(() => []) }));

import { useChatWorkspaceData } from './useChatWorkspaceData';
import { useChats, useLorebooks, useWorlds, useSearchChats } from '../hooks/useWorldVault';
import { useVoices as useVoicesDirect } from '../hooks/useVoices';
import { useCollections } from '../hooks/useCollections';

function wrapper({ children }) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

const args = {
    activeChatId: 'chat-1',
    activeBranch: null,
    chatSearchQuery: '',
    messagePageCount: 1,
    messageSearch: '',
    chatOffset: 0,
};

function renderWorkspace() {
    return renderHook(() => useChatWorkspaceData(args), { wrapper }).result;
}

describe('useChatWorkspaceData surfaces every query failure', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        queryState.current = {};
        useChats.mockReturnValue({ data: [], isError: false, error: null, refetch: vi.fn() });
        useSearchChats.mockReturnValue({ data: null, isError: false, error: null, refetch: vi.fn() });
        useLorebooks.mockReturnValue({ data: [], isError: false, error: null, refetch: vi.fn() });
        useVoicesDirect.mockReturnValue({ data: [], isError: false, error: null, refetch: vi.fn() });
        useWorlds.mockReturnValue({ data: [], isError: false, error: null, refetch: vi.fn() });
        useCollections.mockReturnValue({ data: {}, isError: false, error: null, refetch: vi.fn() });
    });
    afterEach(cleanup);

    it('publishes an empty queryErrors map when every query succeeds', () => {
        const { current } = renderWorkspace();
        expect(current.queryErrors).toEqual({});
    });

    it('records a failed chats query, with its retry', () => {
        const refetch = vi.fn();
        useChats.mockReturnValue({ data: [], isError: true, error: new Error('503 down'), refetch });

        const { current } = renderWorkspace();
        expect(current.queryErrors.chats).toEqual({
            error: expect.any(Error),
            refetch,
            noun: 'chats',
        });
        expect(current.isChatsError).toBe(true);
        expect(current.chatsError.message).toBe('503 down');
        expect(current.refetchChats).toBe(refetch);
    });

    it('records a failed lorebooks query, so "No lorebooks available" is not reachable', () => {
        const refetch = vi.fn();
        useLorebooks.mockReturnValue({ data: [], isError: true, error: new Error('boom'), refetch });

        const { current } = renderWorkspace();
        expect(current.queryErrors.lorebooks.noun).toBe('lorebooks');
        expect(current.queryErrors.lorebooks.refetch).toBe(refetch);
    });

    it('records voices and worlds failures, the two selectors gated on length > 0', () => {
        useVoicesDirect.mockReturnValue({ data: [], isError: true, error: new Error('v'), refetch: vi.fn() });
        useWorlds.mockReturnValue({ data: [], isError: true, error: new Error('w'), refetch: vi.fn() });

        const { current } = renderWorkspace();
        expect(Object.keys(current.queryErrors).sort()).toEqual(['voices', 'worlds']);
    });

    it('records a failed search separately from the list it replaces', () => {
        useSearchChats.mockReturnValue({ data: null, isError: true, error: new Error('s'), refetch: vi.fn() });

        const { current } = renderWorkspace();
        // Two different failure modes behind one visible list; conflating them
        // is how "No chats yet" survived a failing search.
        expect(current.queryErrors.searchResults.noun).toBe('chat results');
        expect(current.queryErrors.chats).toBeUndefined();
    });

    it('leaves the data arrays alone — a failure is not an empty array', () => {
        useLorebooks.mockReturnValue({ data: [], isError: true, error: new Error('boom'), refetch: vi.fn() });

        const { current } = renderWorkspace();
        // The `= []` default is unchanged and must stay: consumers still need an
        // array to render. The distinction is carried by `queryErrors`, not by
        // changing the shape every consumer already depends on.
        expect(current.lorebooks).toEqual([]);
        expect(current.queryErrors.lorebooks).toBeDefined();
    });

    it('records all 16 failures at once, independently', () => {
        for (const name of FAILABLE) {
            worldVaultMock[name].mockReturnValue({ data: [], isError: true, error: new Error(name), refetch: vi.fn() });
        }
        useVoicesDirect.mockReturnValue({ data: [], isError: true, error: new Error('useVoices'), refetch: vi.fn() });
        useCollections.mockReturnValue({ data: {}, isError: true, error: new Error('useCollections'), refetch: vi.fn() });

        const { current } = renderWorkspace();
        // The prior audit counted 12; the hook actually makes 16 read queries
        // (14 from the world-vault hooks, plus voices and collections).
        expect(Object.keys(current.queryErrors).sort()).toEqual([
            'activeChat', 'availableModels', 'characters', 'chatCollection',
            'chatImages', 'chatJobs', 'chats', 'collectionsMap',
            'defaultLlmConfig', 'lorebooks', 'messagesData', 'personas',
            'searchResults', 'systemPromptData', 'voices', 'worlds',
        ].sort());
        expect(Object.keys(current.queryErrors)).toHaveLength(16);
    });
});
describe('the messages query limit is a pure function of messagePageCount', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        queryState.current = {};
        useChats.mockReturnValue({ data: [], isError: false, error: null, refetch: vi.fn() });
        useSearchChats.mockReturnValue({ data: null, isError: false, error: null, refetch: vi.fn() });
    });

    it('asks for one page of history per unit of the counter', () => {
        renderHook(() => useChatWorkspaceData({ ...args, messagePageCount: 1 }), { wrapper });
        expect(useMessagesMock()).toHaveBeenLastCalledWith(
            'chat-1',
            expect.objectContaining({ limit: 100 })
        );
    });

    it('scales the limit with the counter, which is the whole point of it', () => {
        renderHook(() => useChatWorkspaceData({ ...args, messagePageCount: 8 }), { wrapper });
        expect(useMessagesMock()).toHaveBeenLastCalledWith(
            'chat-1',
            expect.objectContaining({ limit: 800 })
        );
    });
});

/**
 * `useMessages` is called through the mocked `useWorldVault`, so it is captured
 * by name from the shared mock object rather than imported directly — importing
 * it would bind the mock at import time and miss the later `mockReturnValue`.
 */
function useMessagesMock() {
    return worldVaultMock.useMessages;
}
