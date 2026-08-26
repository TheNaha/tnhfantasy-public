import {
    useChats, useChat, useMessages, useSearchChats, useLorebooks, useCharacters, usePersonas,
    useLLMAvailableModels, useLLMDefaultProvider, useChatSystemPrompt,
    useCharacterCollection, useChatImages, useChatJobs,
} from '../hooks/useWorldVault';
import { useVoices } from '../hooks/useVoices';
import { useCollections } from '../hooks/useCollections';
import { useActiveChatStreams } from '../hooks/useStreamingJobs';

const CHAT_PAGE_SIZE = 50;

/**
 * Centralizes all read-side data fetching for the chat workspace so the
 * provider stays focused on local UI state and action handlers.
 * Returns the raw query results (plus the derived stream arrays) keyed by the
 * same names the provider has always exposed.
 */
export function useChatWorkspaceData({ activeChatId, activeBranch, chatSearchQuery, messagePageCount, messageSearch, chatOffset }) {
    const { data: chats, isLoading: isChatsLoading } = useChats({ limit: CHAT_PAGE_SIZE, offset: chatOffset });
    const { data: searchResults } = useSearchChats(chatSearchQuery);
    const { data: messagesData = [] } = useMessages(
        activeChatId,
        { limit: messagePageCount * 100, offset: 0, branchId: activeBranch, search: messageSearch || null }
    );
    const { data: activeChat } = useChat(activeChatId);
    const { data: lorebooks = [] } = useLorebooks();
    const { data: characters = [] } = useCharacters();
    const { data: personas = [] } = usePersonas();
    const { data: availableModels = [] } = useLLMAvailableModels();
    const { data: defaultLlmConfig } = useLLMDefaultProvider();
    const { data: systemPromptData } = useChatSystemPrompt(activeChatId);
    const { data: chatCollection } = useCharacterCollection(activeChat?.character_id);
    const { data: chatImages = [] } = useChatImages(activeChatId);
    const { data: collectionsMap = {} } = useCollections('chat');
    const { data: voices = [] } = useVoices();
    const { data: chatJobs = [] } = useChatJobs(activeChatId);

    const activeStreamEntries = useActiveChatStreams(activeChatId);
    const activeStreams = activeStreamEntries
        .filter(item => item.jobData?.status === 'running')
        .map(item => ({ _key: `stream-${item.jobId}`, jobId: item.jobId, jobData: item.jobData }));

    return {
        CHAT_PAGE_SIZE,
        chats,
        isChatsLoading,
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
        activeStreamEntries,
        activeStreams,
    };
}
