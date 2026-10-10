import { useMemo } from 'react';
import {
    useChats, useChat, useMessages, useSearchChats, useLorebooks, useCharacters, usePersonas,
    useLLMAvailableModels, useLLMDefaultProvider, useChatSystemPrompt,
    useCharacterCollection, useChatImages, useChatJobs, useWorlds,
} from '../hooks/useWorldVault';
import { useVoices } from '../hooks/useVoices';
import { useCollections } from '../hooks/useCollections';

const CHAT_PAGE_SIZE = 50;

/**
 * Centralizes all read-side data fetching for the chat workspace so the
 * provider stays focused on local UI state and action handlers.
 * Returns the raw query results (plus the derived stream arrays) keyed by the
 * same names the provider has always exposed.
 */

/**
 * The 16 queries behind the chat surface, all destructured with `isError`,
 * `error` and `refetch` below.
 *
 * Every `data` above destructured with a `= []` default, so a rejected request
 * was indistinguishable from an empty one — and every consumer built its
 * emptiness copy on that: "No chats yet", "No lorebooks available", "No
 * locations". A 503 on any of them produced a confident, specific, wrong
 * statement about data the user already owns, and in the sidebar's case a
 * working **+** button next to a library that already had chats.
 *
 * `isError`/`error`/`refetch` are destructured here, once, rather than at the
 * eight-plus call sites that needed them: the consumers receive arrays and a
 * context, so they cannot reach the query object themselves, which is why
 * `rg "isError|QueryErrorState|QueryGate"` over the chat surface returned
 * nothing. Fixing it anywhere else would have meant fixing it in eight places
 * and hoping the ninth was not written next month.
 *
 * The published `queryErrors` map holds an entry only for a query that
 * actually failed, so a consumer asks `queryErrors.lorebooks` rather than
 * remembering which key holds which noun. Each entry carries the refetch, so
 * the shared `QueryErrorState` retry button works without a consumer needing
 * to know which hook produced it.
 */

export function useChatWorkspaceData({ activeChatId, activeBranch, chatSearchQuery, messagePageCount, messageSearch, chatOffset }) {
    // `isError`/`error`/`refetch` on every query, for `queryErrors` below.
    const {
        data: chats, isLoading: isChatsLoading, isError: isChatsError, error: chatsError, refetch: refetchChats,
    } = useChats({ limit: CHAT_PAGE_SIZE, offset: chatOffset });
    const {
        data: searchResults, isError: isSearchError, error: searchError, refetch: refetchSearch,
    } = useSearchChats(chatSearchQuery);
    const {
        data: messagesData = [], isError: isMessagesError, error: messagesError, refetch: refetchMessages,
    } = useMessages(
        activeChatId,
        { limit: messagePageCount * 100, offset: 0, branchId: activeBranch, search: messageSearch || null, tail: true }
    );
    const { data: activeChat, isError: isActiveChatError, error: activeChatError, refetch: refetchActiveChat } = useChat(activeChatId);
    const { data: lorebooks = [], isError: isLorebooksError, error: lorebooksError, refetch: refetchLorebooks } = useLorebooks();
    const { data: characters = [], isError: isCharactersError, error: charactersError, refetch: refetchCharacters } = useCharacters();
    const { data: personas = [], isError: isPersonasError, error: personasError, refetch: refetchPersonas } = usePersonas();
    const {
        data: availableModels = [], isError: isModelsError, error: modelsError, refetch: refetchModels,
    } = useLLMAvailableModels();
    const {
        data: defaultLlmConfig, isError: isDefaultLlmError, error: defaultLlmError, refetch: refetchDefaultLlm,
    } = useLLMDefaultProvider();
    const {
        data: systemPromptData, isError: isSystemPromptError, error: systemPromptError, refetch: refetchSystemPrompt,
    } = useChatSystemPrompt(activeChatId);
    const {
        data: chatCollection, isError: isChatCollectionError, error: chatCollectionError, refetch: refetchChatCollection,
    } = useCharacterCollection(activeChat?.character_id);
    const {
        data: chatImages = [], isError: isChatImagesError, error: chatImagesError, refetch: refetchChatImages,
    } = useChatImages(activeChatId);
    const {
        data: collectionsMap = {}, isError: isCollectionsError, error: collectionsError, refetch: refetchCollections,
    } = useCollections('chat');
    const { data: voices = [], isError: isVoicesError, error: voicesError, refetch: refetchVoices } = useVoices();
    const {
        data: chatJobs = [], isError: isChatJobsError, error: chatJobsError, refetch: refetchChatJobs,
    } = useChatJobs(activeChatId);
    // Only for the New Chat modal's world picker, reached through
    // `ChatContextPanel` → `NewChatModal`. An earlier comment here said this was
    // deliberately excluded from the contextValue memo downstream — it was not,
    // and `worlds` was in both the memo's key list and its dependency array.
    // The comment was the defect: it invited the next reader to "restore" the
    // exclusion by deleting a dependency the context panel genuinely reads.
    const { data: worlds = [], isError: isWorldsError, error: worldsError, refetch: refetchWorlds } = useWorlds();

    /**
     * `{ chats: { error, refetch, noun }, … }` — one entry per FAILED query.
     *
     * A key is absent when its query succeeded, so `queryErrors.lorebooks` is a
     * complete answer to "may I claim this user has no lorebooks". `noun` is
     * carried alongside so a consumer can hand the whole entry to
     * `QueryErrorState` without having to know the key's English.
     *
     * Built inside the memo below rather than in one of its own: a second memo
     * over 32 individual error values is a second dependency list to keep in
     * sync, and this one already names every query it reads.
     */
    const queryErrors = useMemo(() => {
        const map = {};
        for (const [key, noun, isError, error, refetch] of [
            ['chats', 'chats', isChatsError, chatsError, refetchChats],
            ['searchResults', 'chat results', isSearchError, searchError, refetchSearch],
            ['messagesData', 'messages', isMessagesError, messagesError, refetchMessages],
            ['activeChat', 'chat', isActiveChatError, activeChatError, refetchActiveChat],
            ['lorebooks', 'lorebooks', isLorebooksError, lorebooksError, refetchLorebooks],
            ['characters', 'characters', isCharactersError, charactersError, refetchCharacters],
            ['personas', 'personas', isPersonasError, personasError, refetchPersonas],
            ['availableModels', 'language models', isModelsError, modelsError, refetchModels],
            ['defaultLlmConfig', 'language model settings', isDefaultLlmError, defaultLlmError, refetchDefaultLlm],
            ['systemPromptData', 'system prompt', isSystemPromptError, systemPromptError, refetchSystemPrompt],
            ['chatCollection', 'character collection', isChatCollectionError, chatCollectionError, refetchChatCollection],
            ['chatImages', 'chat images', isChatImagesError, chatImagesError, refetchChatImages],
            ['collectionsMap', 'collections', isCollectionsError, collectionsError, refetchCollections],
            ['voices', 'voices', isVoicesError, voicesError, refetchVoices],
            ['chatJobs', 'chat jobs', isChatJobsError, chatJobsError, refetchChatJobs],
            ['worlds', 'worlds', isWorldsError, worldsError, refetchWorlds],
        ]) {
            if (isError) map[key] = { error, refetch, noun };
        }
        return map;
    }, [
        // Every failure signal above. Omitting these is not a lint warning, it
        // is a chat sidebar that keeps claiming a failed fetch left you with no
        // chats — `queryErrors` is derived from all of them.
        isChatsError, chatsError, refetchChats,
        isSearchError, searchError, refetchSearch,
        isMessagesError, messagesError, refetchMessages,
        isActiveChatError, activeChatError, refetchActiveChat,
        isLorebooksError, lorebooksError, refetchLorebooks,
        isCharactersError, charactersError, refetchCharacters,
        isPersonasError, personasError, refetchPersonas,
        isModelsError, modelsError, refetchModels,
        isDefaultLlmError, defaultLlmError, refetchDefaultLlm,
        isSystemPromptError, systemPromptError, refetchSystemPrompt,
        isChatCollectionError, chatCollectionError, refetchChatCollection,
        isChatImagesError, chatImagesError, refetchChatImages,
        isCollectionsError, collectionsError, refetchCollections,
        isVoicesError, voicesError, refetchVoices,
        isChatJobsError, chatJobsError, refetchChatJobs,
        isWorldsError, worldsError, refetchWorlds,
    ]);

    return useMemo(() => ({
        CHAT_PAGE_SIZE,
        chats,
        isChatsLoading,
        // Parallel to `isChatsLoading`, which has always been published. The
        // sidebar's "No chats yet" branch needs exactly this pair.
        isChatsError,
        chatsError,
        refetchChats,
        queryErrors,
        searchResults,
        messagesData,
        activeChat,
        lorebooks,
        characters,
        personas,
        availableModels,
        defaultLlmConfig,
        systemPromptData,
        chatCollection,
        chatImages,
        collectionsMap,
        voices,
        chatJobs,
        worlds,
    }), [
        chats, isChatsLoading, isChatsError, chatsError, refetchChats, queryErrors,
        searchResults, messagesData, activeChat,
        lorebooks, characters, personas, availableModels, defaultLlmConfig,
        systemPromptData, chatCollection, chatImages, collectionsMap,
        voices, chatJobs, worlds,
    ]);
}