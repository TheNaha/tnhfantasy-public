/* eslint-disable react-refresh/only-export-components */
import React, { createContext, useContext, useState, useEffect, useRef, useCallback, useMemo } from 'react';
import toast from 'react-hot-toast';
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useChatWorkspaceData } from '../hooks/useChatWorkspaceData';
import { useChatWorkspaceMutations } from '../hooks/useChatWorkspaceMutations';
import { useLLMJobResult } from '../hooks/useLLMJobResult';
import { filesApi } from '../api/files';
import { useAddImagesToCollection } from '../hooks/useCollections';
import { useWorldVaultStore } from '../store/worldVaultStore';
import { useConfirmation } from '../store/confirmationStore';
import useSettingsStore from '../store/settingsStore';
import { useWebSocket, EventTypes, cancelJob } from '../api/websocket';
import { useDebounce } from '../hooks/useDebounce';
import { useChatStreaming } from '../hooks/useChatStreaming';
import { CHAT_LIST_KEY } from '../hooks/useChats';
import { setStreamingJob, useActiveChatStreams } from '../hooks/useStreamingJobs';
import { buildContinuationTimeline } from '../utils/continuationText';
import { COMMANDS } from '../components/chat/chatCommands';
import { warnIfWorldIgnored, WORLD_IGNORED_MESSAGE } from '../utils/worldLinkWarning';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';

const ChatWorkspaceContext = createContext(null);

/**
 * Keep a stable identity for a react-query mutation result.
 *
 * react-query v5's `useMutation` returns `{ ...result, mutate, mutateAsync }` — a
 * fresh object literal on every render, even when the mutation's state has not
 * changed. These objects are the dependency list of the context `useMemo`
 * below, so they defeated it: the memo recomputed on every render, a new
 * context object was published, and *every* consumer of `useChatWorkspace()`
 * re-rendered — including `MessageTimeline` and its 600-line `MessageItem`, on
 * every streamed token.
 *
 * The dependency list is every field `MutationObserver` can change, so the
 * identity moves exactly when the mutation's observable state does. The
 * consumer API is unchanged: `sendMessageMutation.isPending` still works.
 */
function useStableObject(mutation) {
    // `useMemo` is called unconditionally (an early return for a missing
    // mutation would break the rules of hooks) and the dependencies are read
    // defensively: some of these mutation hooks are mocked out in tests and a
    // few are conditionally composed, and the previous plain destructuring
    // tolerated an undefined entry by putting it straight into the context.
    return useMemo(
        () => mutation,
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [
            mutation?.data, mutation?.error, mutation?.status, mutation?.variables,
            mutation?.submittedAt, mutation?.context, mutation?.failureCount, mutation?.failureReason,
            mutation?.isIdle, mutation?.isPending, mutation?.isSuccess, mutation?.isError,
            mutation?.isPaused, mutation?.mutate, mutation?.mutateAsync, mutation?.reset,
        ]
    );
}

export function ChatWorkspaceProvider({ children }) {

    const [mobileTab, setMobileTab] = useState('chat'); // 'chats', 'chat', 'context', 'timeline'
    const [timelineVisible, setTimelineVisible] = useState(false);
    const [chatsCollapsed, setChatsCollapsed] = useState(() => {
        try { return localStorage.getItem('cw.chatsCollapsed') === '1'; } catch { return false; }
    });
    const [contextCollapsed, setContextCollapsed] = useState(() => {
        try { return localStorage.getItem('cw.contextCollapsed') === '1'; } catch { return false; }
    });
    useEffect(() => {
        try { localStorage.setItem('cw.chatsCollapsed', chatsCollapsed ? '1' : '0'); } catch { /* ignore */ }
    }, [chatsCollapsed]);
    useEffect(() => {
        try { localStorage.setItem('cw.contextCollapsed', contextCollapsed ? '1' : '0'); } catch { /* ignore */ }
    }, [contextCollapsed]);
    const [message, setMessage] = useState('');
    const [renamingChatId, setRenamingChatId] = useState(null);
    const [renameValue, setRenameValue] = useState('');
    const hasCreatedChatRef = useRef(false);
    const [isGeneratingScene, setIsGeneratingScene] = useState(false);
    const [sceneJobId, setSceneJobId] = useState(null);
    const sceneJobIdRef = useRef(null);
    // The watchdog for `handleGenerateScene`. Declared beside `sceneJobId` and
    // cleared in the same effect that clears `suggestSafetyTimerRef`, so a
    // pending timer cannot fire after unmount.
    const sceneSafetyTimerRef = useRef(null);
    const [pendingAttachment, setPendingAttachment] = useState(null);
    const [isUploading, setIsUploading] = useState(false);
    const [agenticMode, setAgenticMode] = useState(true);
    const [narrateMode, setNarrateMode] = useState(false);
    const [isGeneratingTitle, setIsGeneratingTitle] = useState(false);
    const [greetingModal, setGreetingModal] = useState(null);
    const [showNewChatModal, setShowNewChatModal] = useState(false);
    const [showCharacterDetails, setShowCharacterDetails] = useState(false);
    // The chat workspace had no way to CREATE or EDIT a lorebook or a location.
    // `ChatContextPanel` could only link a row that already existed, and the
    // entity inspector's pencil — which every other surface renders with the
    // tooltip "Edit <name>" — opened a read-only details modal. `StorySandbox`
    // keeps this state and mounts the same three modals; the chat workspace
    // mounts them in `ChatWorkspace.jsx` for the same reason.
    const [editingCharacter, setEditingCharacter] = useState(null);
    const [editingLorebook, setEditingLorebook] = useState(null);
    const [showLorebookModal, setShowLorebookModal] = useState(false);
    const [editingLocation, setEditingLocation] = useState(null);
    const [showLocationModal, setShowLocationModal] = useState(false);
    const [showScenesModal, setShowScenesModal] = useState(false);
    const [sceneTab, setSceneTab] = useState('chat');
    const [showMoreTools, setShowMoreTools] = useState(false);
    const [avatarModalSrc, setAvatarModalSrc] = useState(null);
    const handleAvatarClick = useCallback((url) => setAvatarModalSrc(url), []);
    const fileInputRef = useRef(null);
    const messagesEndRef = useRef(null);
    const listContainerRef = useRef(null);
    // True while the message list is scrolled to (or near) the bottom, so the
    // stream only auto-scrolls for a reader who is following it.
    const isPinnedToBottomRef = useRef(true);
    const textareaRef = useRef(null);
    const location = useLocation();
    const navigate = useNavigate();
    const { chatId: urlChatId } = useParams();
    const [searchParams, setSearchParams] = useSearchParams();

    // Select the one field the send path actually sends. Publishing the whole
    // settings object on the context value re-rendered all ~20
    // useChatWorkspace() consumers — the virtualised MessageTimeline included —
    // on any settings change, and the memo carrying them has ~210 dependencies.
    // The two former consumers of `context.settings` (MessageTimeline and
    // ChatWorkspaceLayout) read `ai.ttsEnabled` and now select it themselves.
    const generatorCheckpoint = useSettingsStore((s) => s.settings?.generator?.defaultCheckpoint);
    
    const queryClient = useQueryClient();
    const activeChatId = useWorldVaultStore(state => state.activeChatId);
    const setActiveChatId = useWorldVaultStore(state => state.setActiveChat);

    const [activeBranch, setActiveBranchState] = useState(() => searchParams.get('branch'));

    const setActiveBranch = useCallback((branchId) => {
        setActiveBranchState(branchId);
        setSearchParams(prev => {
            if (branchId) prev.set('branch', branchId);
            else prev.delete('branch');
            return prev;
        }, { replace: true });
    }, [setSearchParams]);

    useEffect(() => {
        const urlBranch = searchParams.get('branch');
        if (urlBranch && urlBranch !== activeBranch) {
            setActiveBranchState(urlBranch);
        }
    }, [searchParams]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        // URL -> store, only.
        //
        // This used to be a two-way sync, and that is why you could not change
        // chats. The store is what `ChatSidebar` sets on click; the URL is what
        // this effect treated as authoritative. Selecting a second chat set the
        // store while the URL still held the first, so the next render came back
        // through here and reset the store to the URL's chat — the selection was
        // reverted the instant it was made, with no error and no console warning.
        //
        // Deleting a chat hit the same fight from the other side: the handler
        // moved the store to the next chat, this effect pulled it back to the
        // deleted one, and its queries 404'd and retried — the "the chat is gone"
        // loop.
        //
        // So the URL is now the single writer for *which* chat is open, and
        // `selectChat` (below) is the only thing that changes it. A deep link
        // still works, because the URL drives the store.
        if (urlChatId && activeChatId !== urlChatId) {
            setActiveChatId(urlChatId);
        }
    }, [activeChatId, urlChatId, setActiveChatId]);

    /**
     * Select a chat: one navigation, which is the only thing that changes it.
     *
     * Every call site went through the bare store setter, which is why the URL
     * and the store could disagree. `navigate` is used rather than
     * `setSearchParams` so the chat id stays a path segment and the address bar
     * is shareable, matching the `/chat/:id` route.
     */
    const selectChat = useCallback(
        (chatId) => {
            if (!chatId || chatId === activeChatId) return;
            navigate(`/chat/${chatId}`);
        },
        [activeChatId, navigate]
    );

    const [suggestJobId, setSuggestJobId] = useState(null);
    const suggestJobIdRef = useRef(null);
    const suggestSafetyTimerRef = useRef(null);
    const titlePollCancelledRef = useRef(false);

    useEffect(() => {
        return () => {
            if (suggestSafetyTimerRef.current) {
                clearTimeout(suggestSafetyTimerRef.current);
            }
            if (sceneSafetyTimerRef.current) {
                clearTimeout(sceneSafetyTimerRef.current);
            }
        };
    }, []);

    // Declared before the chat-switch reset below, which closes over all three:
    // the effect only ran because the callback executes after the body
    // finishes, so hoisting the declarations is what keeps it from becoming a
    // TDZ ReferenceError the day anyone reorders this block.
    const [activeCommand, setActiveCommand] = useState(null);
    const [targetCharacterId, setTargetCharacterId] = useState('');
    const [turnDirective, setTurnDirective] = useState('');

    const previousChatIdRef = useRef(activeChatId);
    useEffect(() => {
        if (previousChatIdRef.current && previousChatIdRef.current !== activeChatId) {
            setMessage('');
            setTurnDirective('');
            setPendingAttachment(null);
            setActiveCommand(null);
            setTargetCharacterId('');
            setMessageSearch('');
            setActiveBranchState(null);
            // `messagePageCount` is how far back THIS chat has been scrolled, so
            // it is per-chat state and was the only field this reset did not
            // clear. `useChatWorkspaceData` keys its query on it, so a user who
            // scrolled back in a long chat and then opened a 12-message one left
            // the counter at 8 and opened with `limit=400` — eight pages of
            // history fetched for twelve messages, re-run on every switch.
            setMessagePageCount(1);
        }
        previousChatIdRef.current = activeChatId;
    }, [activeChatId]);

    useEffect(() => {
        suggestJobIdRef.current = suggestJobId;
    }, [suggestJobId]);

    useEffect(() => {
        // Cancel any in-flight title-generation poll when switching chats.
        // triggerAutoTitle resets the flag to false at the start of a new run.
        titlePollCancelledRef.current = true;
        setIsGeneratingTitle(false);
    }, [activeChatId]);

    const CHAT_PAGE_SIZE = 50;
    const [chatOffset, setChatOffset] = useState(0);
    const [chatSearchQuery, setChatSearchQuery] = useState('');

    const MESSAGE_PAGE_SIZE = 100;
    const MAX_MESSAGE_PAGES = 5;
    const [messagePageCount, setMessagePageCount] = useState(1);
    const [messageSearch, setMessageSearch] = useState('');

    // The sidebar's own input stays on the raw value (a debounced one would
    // lag behind the caret); only the query it triggers is debounced, and the
    // list switches on the same debounced value so it cannot flash empty.
    const debouncedChatSearchQuery = useDebounce(chatSearchQuery, 300);

    const cwData = useChatWorkspaceData({ activeChatId, activeBranch, chatSearchQuery: debouncedChatSearchQuery, messagePageCount, messageSearch, chatOffset });
    const {
        chats, isChatsLoading, isChatsError, chatsError, refetchChats, queryErrors,
        searchResults, messagesData, activeChat, lorebooks, characters, worlds,
        personas, availableModels, defaultLlmConfig, systemPromptData, chatCollection, chatImages,
        collectionsMap, voices, chatJobs,
    } = cwData;
    const messages = messagesData;
    const cwMutations = useChatWorkspaceMutations();
    const activeStreamEntries = useActiveChatStreams(activeChatId);
    const runningStreamEntries = useMemo(
        () => activeStreamEntries.filter(item => item.jobData && item.jobData.status !== 'completed' && item.jobData.status !== 'failed' && item.jobData.status !== 'cancelled'),
        [activeStreamEntries]
    );
    // A continuation is a second LLM pass over the same beat: its tokens belong
    // in the bubble they continue, not in a second "X is thinking…" row.
    const { items: timelineMessages, parentJobIds: parentJobIdsInMessages } = useMemo(
        () => buildContinuationTimeline(messages, runningStreamEntries),
        [messages, runningStreamEntries]
    );
    const activeStreams = useMemo(
        () => runningStreamEntries
            // If the parent message is not on the loaded page there is no
            // bubble to merge into; fall back to the standalone placeholder so
            // the output is never invisible.
            .filter(item => {
                const parentJobId = item.jobData?.continuationOfJobId;
                return !parentJobId || !parentJobIdsInMessages.has(parentJobId);
            })
            .map(item => ({ _key: `stream-${item.jobId}`, jobId: item.jobId, jobData: item.jobData })),
        [runningStreamEntries, parentJobIdsInMessages]
    );
    const isGeneratingReply = useMemo(
        () => runningStreamEntries.some(item => item.jobData?.taskType !== 'image' && item.jobData?.type !== 'image'),
        [runningStreamEntries]
    );
    const {
        sendMessageMutation: rawSendMessageMutation, createChatMutation: rawCreateChatMutation,
        exportJsonlMutation: rawExportJsonlMutation, importChatMutation: rawImportChatMutation,
        exportToStoryMutation: rawExportToStoryMutation,
        deleteChatMutation: rawDeleteChatMutation, renameChatMutation: rawRenameChatMutation,
        updateChatMutation: rawUpdateChatMutation, editMessageMutation: rawEditMessageMutation,
        rollbackMutation: rawRollbackMutation, regenerateMutation: rawRegenerateMutation,
        patchCharacterMutation: rawPatchCharacterMutation, deleteMessageMutation: rawDeleteMessageMutation,
        impersonateMutation: rawImpersonateMutation, pinMessageMutation: rawPinMessageMutation,
        swipeMessageMutation: rawSwipeMessageMutation, generateSwipeMutation: rawGenerateSwipeMutation,
        narrateMutation: rawNarrateMutation, illustrateMutation: rawIllustrateMutation,
        generateSceneMutation: rawGenerateSceneMutation, suggestReplyMutation: rawSuggestReplyMutation,
    } = cwMutations;

    // react-query v5's `useMutation` returns `{ ...result, mutate, mutateAsync }` —
    // a fresh object literal on every render, even when the mutation's state has
    // not changed. These objects are the dependency list of the context
    // `useMemo` below, so they defeated it: the memo recomputed on every render,
    // a new context object was published, and *every* consumer of
    // `useChatWorkspace()` re-rendered — including `MessageTimeline` and its
    // 600-line `MessageItem`, on every streamed token.
    //
    // `useStableObject` keeps the previous identity while the contents are
    // shallow-equal, so the context only changes when a mutation genuinely
    // changes state (isPending, error, data). The consumer API is unchanged:
    // `sendMessageMutation.isPending` still works.
    const sendMessageMutation = useStableObject(rawSendMessageMutation);
    const createChatMutation = useStableObject(rawCreateChatMutation);
    const exportJsonlMutation = useStableObject(rawExportJsonlMutation);
    const importChatMutation = useStableObject(rawImportChatMutation);
    const exportToStoryMutation = useStableObject(rawExportToStoryMutation);
    const deleteChatMutation = useStableObject(rawDeleteChatMutation);
    const renameChatMutation = useStableObject(rawRenameChatMutation);
    const updateChatMutation = useStableObject(rawUpdateChatMutation);
    const editMessageMutation = useStableObject(rawEditMessageMutation);
    const rollbackMutation = useStableObject(rawRollbackMutation);
    const regenerateMutation = useStableObject(rawRegenerateMutation);
    const patchCharacterMutation = useStableObject(rawPatchCharacterMutation);
    const deleteMessageMutation = useStableObject(rawDeleteMessageMutation);
    const impersonateMutation = useStableObject(rawImpersonateMutation);
    const pinMessageMutation = useStableObject(rawPinMessageMutation);
    const swipeMessageMutation = useStableObject(rawSwipeMessageMutation);
    const generateSwipeMutation = useStableObject(rawGenerateSwipeMutation);
    const narrateMutation = useStableObject(rawNarrateMutation);
    const illustrateMutation = useStableObject(rawIllustrateMutation);
    const generateSceneMutation = useStableObject(rawGenerateSceneMutation);
    const suggestReplyMutation = useStableObject(rawSuggestReplyMutation);
    const addImagesToCollectionMutation = useAddImagesToCollection();

    const activeChatList = useMemo(
        () => debouncedChatSearchQuery.trim() ? (searchResults || []) : chats,
        [debouncedChatSearchQuery, searchResults, chats]
    );
    const hasMoreChats = useMemo(
        () => chats?.length === CHAT_PAGE_SIZE && !debouncedChatSearchQuery.trim(),
        [chats, debouncedChatSearchQuery]
    );

    const lastLoadedPageFull = messagesData.length === messagePageCount * MESSAGE_PAGE_SIZE;
    const hasMoreMessages = messagePageCount < MAX_MESSAGE_PAGES && lastLoadedPageFull;
        const loadOlderMessages = useCallback(() => {
        setMessagePageCount(c => Math.min(c + 1, MAX_MESSAGE_PAGES));
    }, [setMessagePageCount]);

    const collectionsList = useMemo(
        () => Object.values(collectionsMap).sort((a, b) => (a.name || '').localeCompare(b.name || '')),
        [collectionsMap]
    );

    const listItems = useMemo(
        () => [
            // Index from the map callback, not messages.indexOf(msg): the
            // latter is a linear scan per element, so building this list was
            // O(n^2) — ~125k comparisons at the 500-message cap — and it is
            // recomputed on every streamed token.
            ...timelineMessages,
            ...activeStreams,
        ],
        [timelineMessages, activeStreams]
    );

    const rowVirtualizer = useVirtualizer({
        count: listItems.length,
        getScrollElement: () => listContainerRef.current,
        estimateSize: () => 120,
        overscan: 8,
    });

    const emptyLorebooks = useMemo(() => [], []);
    const selectedLorebooks = activeChat?.active_lorebook_ids || emptyLorebooks;

    const { subscribe } = useWebSocket();
    const runLLMJob = useLLMJobResult();
    const { confirm } = useConfirmation();

    useEffect(() => {
        const characterId = location.state?.characterId;
        if (characterId && !activeChatId && !hasCreatedChatRef.current) {
            hasCreatedChatRef.current = true;
            const character = characters.find(c => c.id === characterId);
            const hasMultipleGreetings = character && 
                (character.alternate_greetings?.length > 0);
            
            if (hasMultipleGreetings) {
                setGreetingModal({
                    character,
                    onCreate: async (selectedGreeting) => {
                        setGreetingModal(null);
                        const chat = await createChatMutation.mutateAsync({ 
                            name: 'New Chat', 
                            character_id: characterId,
                            override_greeting: selectedGreeting 
                        });
                        selectChat(chat.id);
                    }
                });
            } else {
                createChatMutation.mutate(
                    { name: 'New Chat', character_id: characterId },
                    {
                        onSuccess: (chat) => {
                            selectChat(chat.id);
                        },
                        onError: () => { hasCreatedChatRef.current = false; }
                    }
                );
            }
        }
    }, [location.state?.characterId, characters, activeChatId, createChatMutation, setActiveChatId, selectChat]);

    // Bootstrap only: no chat is open and the list has one. Deliberately the raw
    // setter, because the URL is empty here and the effect above turns the store
    // value into the URL. Navigating directly would work too, but keeping the
    // "URL is the writer" rule means exactly one place changes the URL.
    useEffect(() => {
        if (!urlChatId && Array.isArray(chats)) {
            if (chats.length > 0) {
                const targetId = activeChatId && chats.some(c => c.id === activeChatId)
                    ? activeChatId
                    : chats[0].id;
                setActiveChatId(targetId);
                navigate(`/chat/${targetId}`, { replace: true });
            } else {
                setActiveChatId(null);
            }
        }
    }, [urlChatId, chats, activeChatId, navigate, setActiveChatId]);

    useChatStreaming({
        activeChatId,
        suggestJobIdRef,
        setMessage,
        setSuggestJobId,
        sceneJobIdRef,
        setSceneJobId,
        setIsGeneratingScene
    });

    useEffect(() => {
        const el = listContainerRef.current;
        if (!el) return undefined;
        const onScroll = () => {
            const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
            isPinnedToBottomRef.current = distanceFromBottom < 80;
        };
        onScroll();
        el.addEventListener('scroll', onScroll, { passive: true });
        return () => el.removeEventListener('scroll', onScroll);
    }, []);

    useEffect(() => {
        // `activeStreamEntries` changes identity per streamed token, so this
        // used to force a layout on every one of them and drag the viewport
        // with it. Only follow the stream when the user is already at the
        // bottom; scrolling up to read history now stays put.
        const hasStreaming = activeStreamEntries.length > 0;
        if (hasStreaming && !isPinnedToBottomRef.current) return;
        messagesEndRef.current?.scrollIntoView({ behavior: hasStreaming ? 'auto' : 'smooth', block: 'end' });
    }, [messages, activeStreamEntries]);

    useEffect(() => {
        // Debounced resize — avoids layout thrashing on mobile with every keystroke
        const timer = setTimeout(() => {
            if (textareaRef.current) {
                textareaRef.current.style.height = 'auto';
                textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
            }
        }, 150);
        return () => clearTimeout(timer);
    }, [message]);

    const handleSendMessage = useCallback(async () => {
        // Guard against a second send while the first is still in flight. The
        // Enter key called this directly and only the send *button* consulted
        // `canSend`, so a double-Enter — which is what a fast typist or an
        // impatient one does — produced two identical user messages and two
        // paid LLM jobs for one thought. Neither chat nor story write routes
        // carry an Idempotency-Key, so the server has no way to collapse them.
        if (sendMessageMutation.isPending || isGeneratingReply) return;

        const msgContentRaw = message.trim();
        if (!msgContentRaw && !pendingAttachment && !activeCommand?.noArgs) {
            toast.error('Message cannot be empty');
            return;
        }

        let chatIdToUse = activeChatId;
        if (!chatIdToUse) {
            try {
                const newChat = await createChatMutation.mutateAsync({ name: 'New Chat' });
                chatIdToUse = newChat.id;
                selectChat(newChat.id);
            } catch {
                toast.error('Failed to create chat');
                return;
            }
        }

        const attachmentFilename = pendingAttachment?.filename || null;
        const currentCommand = activeCommand;
        
        let msgContent = msgContentRaw;
        let role = 'user';
        let noReply = false;
        
        if (currentCommand) {
            const cmd = currentCommand.cmd;
            const arg = msgContentRaw;
            
            if (cmd === '/silent') {
                noReply = true;
                msgContent = arg;
                if (!msgContent && !attachmentFilename) { toast.error("Provide message text"); return; }
            } else if (cmd === '/story') {
                noReply = true;
                role = 'story';
                msgContent = arg;
                if (!msgContent && !attachmentFilename) { toast.error("Provide story text"); return; }
            } else if (cmd === '/puppet' || cmd === '/impersonate') {
                noReply = true;
                role = 'char';
                msgContent = arg;
                if (!msgContent && !attachmentFilename) { toast.error("Provide character text"); return; }
            } else if (cmd === '/time' || cmd === '/fastforward') {
                if (!arg) { toast.error("Provide a time"); return; }
                try {
                    await updateChatMutation.mutateAsync({ chatId: chatIdToUse, story_time: arg });
                    setMessage('');
                    setPendingAttachment(null);
                    setActiveCommand(null);
                } catch { toast.error("Failed to update time"); }
                return;
            } else if (cmd === '/location') {
                if (!arg) { toast.error("Provide a location"); return; }
                try {
                    await updateChatMutation.mutateAsync({ chatId: chatIdToUse, story_location: arg });
                    setMessage('');
                    setPendingAttachment(null);
                    setActiveCommand(null);
                } catch { toast.error("Failed to update location"); }
                return;
            } else if (cmd === '/steer' || cmd === '/directive') {
                if (!arg) { toast.error("Provide steering directive"); return; }
                setTurnDirective(arg);
                setMessage('');
                setActiveCommand(null);
                toast.success(`Turn directive staged: "${arg}"`);
                return;
            } else if (cmd === '/me' || cmd === '/action') {
                msgContent = `*${arg}*`;
                if (!arg && !attachmentFilename) { toast.error("Provide action text"); return; }
            } else if (cmd === '/suggest') {
                try {
                    const res = await suggestReplyMutation.mutateAsync({ chatId: chatIdToUse, draft: arg || undefined });
                    setMessage('');
                    setPendingAttachment(null);
                    setActiveCommand(null);
                    if (res.job_id) { setSuggestJobId(res.job_id); }
                } catch { toast.error("Failed to generate suggestion"); }
                return;
            }
        }

        // One key per send attempt. Generated here rather than in the hook so a
        // retry of the SAME attempt reuses it while a second, distinct send gets
        // its own — the same rule the server applies. `handleSendMessage` returns
        // early on `isPending`, so this only fires for a retry that page-level
        // state has already forgotten about (a tab restored by the browser, an
        // offline queue flush), but those are exactly the cases that produce two
        // paid jobs for one sent message.
        const idempotencyKey = crypto.randomUUID();

        try {
            const res = await sendMessageMutation.mutateAsync({
                chatId: chatIdToUse,
                idempotencyKey,
                message: { 
                    role: role, 
                    content: msgContent, 
                    lorebook_ids: selectedLorebooks, 
                    image_path: attachmentFilename, 
                    target_character_id: targetCharacterId || null,
                    agentic: agenticMode,
                    narrate: narrateMode,
                    generator_checkpoint: generatorCheckpoint || null,
                    no_reply: noReply,
                    directive: turnDirective || undefined,
                }
                });
            setMessage('');
            setTurnDirective('');
            setPendingAttachment(null);
            setActiveCommand(null);
            if (res.job_id) {
                setStreamingJob(queryClient, res.job_id, {
                    text: '',
                    status: 'running',
                    chatId: chatIdToUse,
                    directorDecision: res.director_decision || null,
                    contextTrace: res.context_trace || null,
                });
            }
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, chatIdToUse) });
        } catch {
            toast.error('Failed to send message');
        }
    }, [message, pendingAttachment, activeChatId, selectedLorebooks, agenticMode, narrateMode, createChatMutation, sendMessageMutation, queryClient, generatorCheckpoint, updateChatMutation, suggestReplyMutation, activeCommand, targetCharacterId, selectChat, isGeneratingReply, turnDirective]);

    const handleSuggestClick = useCallback(async () => {
        if (!activeChatId) return;
        try {
            const draft = message.trim();
            setMessage('');
            const res = await suggestReplyMutation.mutateAsync({ chatId: activeChatId, draft: draft || undefined });
            if (res.job_id) {
                setSuggestJobId(res.job_id);
            // Safety net: if the completion event is missed (reconnect gap),
            // don't leave the Suggest button disabled forever.
            // Clear any previous timer first. Two suggests inside the safety
            // window left the first one orphaned, and the unmount cleanup only
            // cleared the last — so a stale timer could still fire after the
            // user had moved on, clearing the disabled state mid-suggest.
            if (suggestSafetyTimerRef.current) {
                clearTimeout(suggestSafetyTimerRef.current);
            }
            suggestSafetyTimerRef.current = window.setTimeout(() => {
                    setSuggestJobId((current) => (current === res.job_id ? null : current));
                }, 120000);
            }
        } catch {
            toast.error("Failed to generate suggestion");
        }
    }, [activeChatId, message, suggestReplyMutation]);

    const handleTextChange = useCallback((e) => {
        const val = e.target.value;
        if (!activeCommand && val.startsWith('/')) {
            const spaceIdx = val.indexOf(' ');
            if (spaceIdx !== -1) {
                const cmdString = val.substring(0, spaceIdx).toLowerCase();
                const matchedCmd = COMMANDS.find(c => c.cmd === cmdString);
                if (matchedCmd && !matchedCmd.noArgs) {
                    setActiveCommand(matchedCmd);
                    setMessage(val.substring(spaceIdx + 1));
                    return;
                }
            }
        }
        setMessage(val);
    }, [activeCommand, setMessage]);

    const handleKeyDown = useCallback((e) => {
        if (e.key === 'Backspace' && message === '' && activeCommand) {
            setMessage(activeCommand.cmd + ' ');
            setActiveCommand(null);
            e.preventDefault();
            return;
        }
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSendMessage();
        } else if (e.key === 'Enter' && e.shiftKey && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            handleSendMessage();
        }
    }, [handleSendMessage, message, activeCommand]);

    const handleCancelStreaming = useCallback(async () => {
        // Cancellations must also reach a continuation stream: it has no row of
        // its own, but it is still a live job holding the send button down.
        const activeTextStream = runningStreamEntries.find(item => item.jobData?.taskType !== 'image' && item.jobData?.type !== 'image');
        if (activeTextStream?.jobId) {
            try {
                await cancelJob(activeTextStream.jobId);
                toast('Generation stopped', { icon: '⏹️' });
            } catch (err) {
                console.warn('Failed to cancel job:', err);
            }
        }
    }, [runningStreamEntries]);

    const canSend = useMemo(
        () => !!(message.trim() || pendingAttachment || activeCommand?.noArgs) && !sendMessageMutation.isPending && !isGeneratingReply,
        [message, pendingAttachment, activeCommand, sendMessageMutation, isGeneratingReply]
    );

    const handleGenerateScene = useCallback(async () => {
        if (!activeChatId) return;
        setIsGeneratingScene(true);
        toast.success('Generating scene...', { icon: '📸' });
        try {
            const data = await generateSceneMutation.mutateAsync({ chatId: activeChatId });
            if (data?.job_id) {
                sceneJobIdRef.current = data.job_id;
                setSceneJobId(data.job_id);
                // Safety net, matching the one `/suggest` has had since it was
                // written. Every way this wait can end without a terminal event
                // for the tracked id leaves `isGeneratingScene` true and the
                // button disabled until a full reload: the events are polled, so
                // a job whose id has already been consumed by a previous poll
                // cycle never matches, and the event bus drops rather than
                // queues. Two minutes is generous for a prompt-writing job, and
                // a disabled button is not worth an unbounded hang.
                //
                // The previous timer is cleared first, so generating a scene
                // twice inside the window does not leave the first one orphaned
                // to fire after the user has moved on.
                if (sceneSafetyTimerRef.current) {
                    clearTimeout(sceneSafetyTimerRef.current);
                }
                sceneSafetyTimerRef.current = window.setTimeout(() => {
                    if (sceneJobIdRef.current !== data.job_id) return;
                    sceneJobIdRef.current = null;
                    setSceneJobId(null);
                    setIsGeneratingScene(false);
                    toast('Scene generation did not report back. Check Jobs before retrying.', { icon: '⚠️', duration: 6000 });
                }, 120000);
            } else {
                setIsGeneratingScene(false);
            }
        } catch {
            toast.error('Failed to generate scene');
            setIsGeneratingScene(false);
        }
    }, [activeChatId, generateSceneMutation]);

    const handleIllustrate = useCallback(async () => {
        if (!activeChatId || illustrateMutation.isPending) return;
        const prompt = message.trim();
        try {
            await illustrateMutation.mutateAsync({
                chatId: activeChatId,
                imagePrompt: prompt,
                branchId: activeBranch,
            });
            if (prompt) setMessage('');
            toast.success('Illustration queued...', { icon: '🖼️' });
        } catch {
            toast.error('Failed to start illustration');
        }
    }, [activeChatId, activeBranch, message, illustrateMutation]);

    const handleSaveImageToCollection = useCallback(async (collectionId, path) => {
        if (!collectionId || !path) return;
        try {
            // Through the mutation, not the raw API function. The hook owns the
            // invalidation policy for both the collection list and the per
            // character collection query; calling `addImagesToCollection`
            // directly is what forced this call site to re-implement that
            // policy by hand, and it was the only call site that remembered.
            await addImagesToCollectionMutation.mutateAsync({ collectionId, images: [path] });
            toast.success('Image saved to collection');
        } catch {
            toast.error('Failed to save image');
        }
    }, [addImagesToCollectionMutation]);

    const triggerAutoTitle = useCallback(async () => {
        if (!activeChatId) return;
        titlePollCancelledRef.current = false;
        setIsGeneratingTitle(true);
        toast('Generating title...', { icon: '🤖' });
        try {
            const chatHistory = messages.slice(-5).map(m => `${m.role}: ${m.content}`).join('\n');
            const { text, cancelled } = await runLLMJob({
                workflow: {
                    model: activeChat?.llm_model || defaultLlmConfig?.model_id || null,
                    messages: [
                        { role: 'system', content: 'Generate a short, catchy title (max 5 words) for the following chat. Output ONLY the title, no quotes.' },
                        { role: 'user', content: chatHistory || 'A new conversation.' }
                    ]
                },
                isCancelled: () => titlePollCancelledRef.current,
            });
            if (cancelled) return;
            if (!text) {
                toast.error('Title generation failed');
                return;
            }
            const newTitle = text.replace(/["']/g, '');
            await renameChatMutation.mutateAsync({ chatId: activeChatId, name: newTitle });
            toast.success('Title generated!');
        } catch {
            toast.error('Failed to generate title');
        } finally {
            setIsGeneratingTitle(false);
        }
    }, [activeChatId, messages, defaultLlmConfig, renameChatMutation, runLLMJob, activeChat?.llm_model]);

    const handleCreateChat = useCallback(() => {
        setShowNewChatModal(true);
    }, []);

    const confirmCreateChat = useCallback((config) => {
        if (createChatMutation.isPending) return;
        setShowNewChatModal(false);
        const { chatName, characterId, personaName, personaId, worldId, storyTime, locationId, storyLocation, selectedLorebooks: newSelectedLorebooks } = config;

        const character = characterId ? characters.find(c => c.id === characterId) : null;
        const hasMultipleGreetings = character && (character.alternate_greetings?.length > 0);

        const payload = {
            name: chatName,
            character_id: characterId,
            persona_name: personaName,
            persona_id: personaId || null,
            story_time: storyTime,
            story_location: storyLocation,
            // The wizard sends the location's NAME as `story_location` AND its id
            // here. `story_location` is the free text that becomes the prompt's
            // `Current Location:` line and the only thing the Activity page's
            // location filter compares against; `location_id` is what injects the
            // location's description, atmosphere and tags. Sending one without
            // the other is how a chat ends up with a place named in one sentence
            // and described in none.
            location_id: locationId || null,
            active_lorebook_ids: newSelectedLorebooks
        };
        // Sent whenever a world was picked. `Chat.world_id` is a real column and
        // comes back on the created chat, which is what makes the response the
        // capability check: if the server does not accept the field on create
        // yet, it is dropped and the chat is created without it. So this must
        // never be able to fail the create — `warnIfWorldIgnored` tells the user
        // afterwards instead.
        if (worldId) payload.world_id = worldId;

        if (hasMultipleGreetings) {
            setGreetingModal({
                character,
                onCreate: async (selectedGreeting) => {
                    setGreetingModal(null);
                    const chat = await createChatMutation.mutateAsync({ 
                        ...payload,
                        override_greeting: selectedGreeting 
                    });
                    if (warnIfWorldIgnored(chat, worldId)) toast(WORLD_IGNORED_MESSAGE('chat'));
                    selectChat(chat.id);
                    setMobileTab('chat');
                    toast.success('New chat created');
                }
            });
        } else {
            createChatMutation.mutate(
                payload,
                {
                    onSuccess: (chat) => {
                        if (warnIfWorldIgnored(chat, worldId)) toast(WORLD_IGNORED_MESSAGE('chat'));
                        selectChat(chat.id);
                        setMobileTab('chat');
                        toast.success('New chat created');
                    },
                    onError: () => toast.error('Failed to create chat')
                }
            );
        }
    }, [createChatMutation, characters, setMobileTab, setGreetingModal, setShowNewChatModal, selectChat]);

    const handleAttachmentChange = useCallback(async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        e.target.value = '';
        if (file.size > 20 * 1024 * 1024) { toast.error('File too large (max 20MB)'); return; }
        setIsUploading(true);
        try {
            const formData = new FormData();
            formData.append('file', file);
            const res = await filesApi.uploadChatAttachment(formData);
            setPendingAttachment({ filename: res.filename, name: file.name });
            toast.success('Image attached');
        } catch {
            toast.error('Failed to upload image');
        } finally {
            setIsUploading(false);
        }
    }, [setIsUploading]);

    const handleDeleteChat = useCallback(async (chat) => {
        const ok = await confirm({
            title: 'Delete Chat',
            message: `Are you sure you want to delete "${chat.name || 'this chat'}"? All messages will be permanently lost.`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            await deleteChatMutation.mutateAsync(chat.id);
            if (activeChatId === chat.id) {
                const remaining = chats?.filter(c => c.id !== chat.id) || [];
                if (remaining?.[0]?.id) {
                    setActiveChatId(remaining[0].id);
                    navigate(`/chat/${remaining[0].id}`, { replace: true });
                } else {
                    setActiveChatId(null);
                    navigate('/chat', { replace: true });
                }
            }
            toast.success('Chat deleted');
        } catch {
            toast.error('Failed to delete chat');
        }
    }, [activeChatId, chats, confirm, deleteChatMutation, navigate, setActiveChatId]);

    const startRename = useCallback((chat) => { setRenamingChatId(chat.id); setRenameValue(chat.name || ''); }, []);
    const finishRename = useCallback(async () => {
        if (renamingChatId && renameValue.trim()) {
            try {
                await renameChatMutation.mutateAsync({ chatId: renamingChatId, name: renameValue.trim() });
                toast.success('Chat renamed');
            } catch { toast.error('Failed to rename'); }
        }
        setRenamingChatId(null);
    }, [renamingChatId, renameValue, renameChatMutation]);

    const handleChatUpdate = useCallback((updates) => {
        if (!activeChatId) return;
        updateChatMutation.mutate({ chatId: activeChatId, ...updates });
    }, [activeChatId, updateChatMutation]);

    const handleEditMessage = useCallback(async (msgId, content) => {
        if (!content.trim()) return;
        try {
            await editMessageMutation.mutateAsync({ chatId: activeChatId, msgId, content });
            toast.success('Message updated');
        } catch { toast.error('Failed to update message'); }
    }, [activeChatId, editMessageMutation]);

    const handleRollback = useCallback(async (msgId) => {
        const ok = await confirm({
            title: 'Rollback chat',
            message: 'This will delete this message and everything after it. The LLM reply will regenerate from the remaining message.',
            confirmText: 'Rollback',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            await rollbackMutation.mutateAsync({ chatId: activeChatId, messageId: msgId });
            toast.success('Chat rolled back');
        } catch { toast.error('Failed to rollback'); }
    }, [activeChatId, confirm, rollbackMutation]);

    const handleRegenerate = useCallback(async (msgId) => {
        // The route deletes every message after this one. It was reachable from
        // an 11px hover-revealed icon whose own tooltip said "(Deletes
        // following messages)", with no confirmation — while the sibling
        // rollback, which deletes the same messages, went through `confirm`.
        // A mis-tap truncated the conversation irrecoverably. `msgId` is the
        // first message to be removed.
        const ok = await confirm({
            title: 'Regenerate from here',
            message: 'This will delete this message and everything after it, then generate a new reply.',
            confirmText: 'Regenerate',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            const res = await regenerateMutation.mutateAsync({ chatId: activeChatId, messageId: msgId, directive: turnDirective || undefined });
            if (turnDirective) setTurnDirective('');
            if (res?.job_id) setStreamingJob(queryClient, res.job_id, { text: '', status: 'running', chatId: activeChatId, type: 'llm' });
        } catch { toast.error('Failed to regenerate'); }
    }, [activeChatId, confirm, regenerateMutation, queryClient, turnDirective]);

    const handleImpersonate = useCallback(async (hint = '') => {
        if (!activeChatId) return;
        try {
            const res = await impersonateMutation.mutateAsync({ chatId: activeChatId, hint });
            if (res?.job_id) {
                setStreamingJob(queryClient, res.job_id, { text: '', status: 'running', chatId: activeChatId, type: 'impersonation' });
                toast('Impersonating...', { icon: '👤' });
            }
        } catch { toast.error('Impersonation failed'); }
    }, [activeChatId, impersonateMutation, queryClient]);

    const handlePinMessage = useCallback(async (msgId, currentlyPinned) => {
        try {
            await pinMessageMutation.mutateAsync({ chatId: activeChatId, msgId, pinned: !currentlyPinned });
            toast.success(currentlyPinned ? 'Message unpinned' : 'Message pinned — won\'t be pruned from context');
        } catch { toast.error('Failed to pin message'); }
    }, [activeChatId, pinMessageMutation]);

    const handleSwipe = useCallback(async (msgId, direction, index) => {
        try {
            await swipeMessageMutation.mutateAsync({ chatId: activeChatId, msgId, direction, index });
        } catch { toast.error('Swipe failed'); }
    }, [activeChatId, swipeMessageMutation]);

    const handleGenerateSwipe = useCallback(async (msgId) => {
        try {
            const res = await generateSwipeMutation.mutateAsync({ chatId: activeChatId, msgId, directive: turnDirective || undefined });
            if (turnDirective) setTurnDirective('');
            if (res?.job_id) {
                setStreamingJob(queryClient, res.job_id, { text: '', status: 'running', chatId: activeChatId, type: 'llm' });
                toast('Generating alternate reply...', { icon: '✨' });
            }
        } catch { toast.error('Failed to generate swipe'); }
    }, [activeChatId, generateSwipeMutation, queryClient, turnDirective]);

    const handleGenerateTTS = useCallback(async (msgId, voiceId) => {
        const voiceName = voiceId ? voices.find(v => v.id === voiceId)?.name : null;
        try {
            await narrateMutation.mutateAsync({ chatId: activeChatId, msgId, voiceId });
            toast.success(voiceName ? `TTS started with ${voiceName}` : 'TTS generation started');
        } catch {
            toast.error('Failed to generate TTS');
        }
    }, [activeChatId, narrateMutation, voices]);

    const handleMessageIllustrate = useCallback(async (msgId) => {
        try {
            const msg = messages.find(m => m.id === msgId);
            const res = await illustrateMutation.mutateAsync({
                chatId: activeChatId,
                imagePrompt: msg?.content || '',
                // The thread the message lives on, NOT the thread currently being
                // read. Illustrating a message from another fork files the image on
                // that message's thread, where the user is looking.
                branchId: msg?.branch_id || activeBranch,
            });
            if (res?.job_id) {
                setStreamingJob(queryClient, res.job_id, { text: '', status: 'running', chatId: activeChatId, type: 'image' });
                toast.success('Illustration started', { icon: '✨' });
            }
        } catch { toast.error('Failed to start illustration'); }
    }, [activeChatId, activeBranch, messages, illustrateMutation, queryClient]);

    const handleDeleteMessage = useCallback(async (msgId) => {
        try {
            await deleteMessageMutation.mutateAsync({ chatId: activeChatId, msgId });
            toast.success('Message deleted');
        } catch {
            toast.error('Failed to delete message');
        }
    }, [activeChatId, deleteMessageMutation]);

    const handleExportChatJsonl = useCallback(async () => {
        if (!activeChatId) { toast.error('No active chat to export'); return; }
        try {
            const { blob, filename } = await exportJsonlMutation.mutateAsync({
                chatId: activeChatId,
                chatName: activeChat?.name,
            });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
            toast.success(`Exported ${filename} (SillyTavern-compatible)`);
        } catch (err) {
            toast.error(err.message || 'Failed to export JSONL');
        }
    }, [activeChatId, activeChat?.name, exportJsonlMutation]);

    const handleExportToStory = useCallback(async () => {
        if (!activeChatId) { toast.error('No active chat to export'); return; }
        try {
            const res = await exportToStoryMutation.mutateAsync(activeChatId);
            toast.success(`Exported to story: "${res.title}"`);
            if (res.story_id) {
                navigate(`/story/${res.story_id}`);
            }
        } catch (err) {
            toast.error(err?.message || 'Failed to export chat to story');
        }
    }, [activeChatId, exportToStoryMutation, navigate]);

    const isImportingChat = importChatMutation.isPending;
    const handleImportChatFile = useCallback(async (file) => {
        if (!file) return;
        const formData = new FormData();
        formData.append('file', file);
        try {
            const chat = await importChatMutation.mutateAsync(formData);
            // Only the list changed: the imported chat has no cached queries
            // yet, and the root key would refetch every open chat's prompt
            // assembly.
            queryClient.invalidateQueries({ queryKey: CHAT_LIST_KEY });
            selectChat(chat.id);
            toast.success(`Imported "${chat.name}"`);
        } catch (err) {
            toast.error(err.message || 'Failed to import chat');
        }
    }, [importChatMutation, queryClient, selectChat]);

    const linkedCharacter = characters.find(c => c.id === activeChat?.character_id);

    const openLorebookModal = useCallback((lorebook) => {
        setEditingLorebook(lorebook ?? null);
        setShowLorebookModal(true);
    }, []);

    const closeLorebookModal = useCallback(() => {
        setEditingLorebook(null);
        setShowLorebookModal(false);
    }, []);

    const openLocationModal = useCallback((location) => {
        setEditingLocation(location ?? null);
        setShowLocationModal(true);
    }, []);

    const closeLocationModal = useCallback(() => {
        setEditingLocation(null);
        setShowLocationModal(false);
    }, []);

    const handleSaveCharacter = useCallback(async (form) => {
        // `_avatarFile` is a local File handle the modal keeps on the form; it is
        // not a field the character route accepts. `CharacterModal` passes the raw
        // form to `onSave`, so stripping it is the caller's job — `Characters.jsx`
        // and `StorySandbox` both do it, and a PATCH carrying it would 422.
        const { _avatarFile, ...payload } = form;
        if (!editingCharacter) return null;
        const saved = await patchCharacterMutation.mutateAsync({ id: editingCharacter.id, ...payload });
        setEditingCharacter(null);
        return saved;
    }, [editingCharacter, patchCharacterMutation]);

    const handleExportChat = useCallback(() => {
        if (!messages.length) { toast.error('No messages to export'); return; }
        const charName = linkedCharacter?.name || 'AI';
        const userName = activeChat?.persona_name || 'You';
        const chatName = activeChat?.name || 'Chat';

        const ROLE_LABEL = {
            user:   userName,
            char:   charName,
            system: '✦ System',
        };

        const lines = [
            `# ${chatName}`,
            linkedCharacter ? `**Character:** ${charName}` : null,
            `**Exported:** ${new Date().toLocaleString()}`,
            '',
            '---',
            '',
        ].filter(Boolean);

        for (const msg of messages) {
            const meta = msg.message_metadata || {};
            if (meta.source === 'world_state') {
                const parts = [];
                if (meta.location) parts.push(`📍 ${meta.location}`);
                if (meta.time)     parts.push(`🕐 ${meta.time}`);
                if (parts.length)  lines.push(`\n*— ${parts.join(' · ')} —*\n`);
                continue;
            }
            const label = ROLE_LABEL[msg.role] ?? '✦ System';
            lines.push(`**${label}:**`);
            lines.push(msg.content);
            if (msg.image_path) lines.push(`*[Image: ${msg.image_path}]*`);
            lines.push('');
        }

        const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = `${chatName.replace(/[^a-z0-9_\- ]/gi, '_')}.md`;
        a.click();
        URL.revokeObjectURL(url);
        toast.success('Chat exported as Markdown');
    }, [messages, linkedCharacter, activeChat]);

    const contextValue = useMemo(() => ({
        CHAT_PAGE_SIZE,
        MAX_MESSAGE_PAGES,
        MESSAGE_PAGE_SIZE,
        activeBranch,
        activeChat,
        activeChatId,
        activeChatList,
        activeChatTtsVoiceId: activeChat?.tts_voice_id,
        activeCommand,
        agenticMode,
        availableModels,
        avatarModalSrc,
        canSend,
        characters,
        chatCollection,
        personas,
        chatImages,
        chatJobs,
        chatOffset,
        chatSearchQuery,
        chats,
        chatsCollapsed,
        collectionsList,
        confirm,
        confirmCreateChat,
        closeLocationModal,
        closeLorebookModal,
        contextCollapsed,
        createChatMutation,
        defaultLlmConfig,
        deleteChatMutation,
        deleteMessageMutation,
        editMessageMutation,
        editingCharacter,
        editingLocation,
        editingLorebook,
        emptyLorebooks,
        fileInputRef,
        finishRename,
        generateSceneMutation,
        generateSwipeMutation,
        greetingModal,
        handleAttachmentChange,
        handleAvatarClick,
        handleCancelStreaming,
        handleChatUpdate,
        handleCreateChat,
        handleDeleteChat,
        handleDeleteMessage,
        handleEditMessage,
        handleExportChat,
        handleExportChatJsonl,
        handleExportToStory,
        exportToStoryMutation,
        handleImportChatFile,
        isImportingChat,
        handleGenerateScene,
        handleGenerateSwipe,
        handleGenerateTTS,
        handleIllustrate,
        handleImpersonate,
        handleKeyDown,
        handleMessageIllustrate,
        handlePinMessage,
        handleRegenerate,
        handleRollback,
        handleSaveCharacter,
        handleSaveImageToCollection,
        handleSendMessage,
        handleSuggestClick,
        handleSwipe,
        handleTextChange,
        hasCreatedChatRef,
        hasMoreChats,
        hasMoreMessages,
        illustrateMutation,
        impersonateMutation,
        // The error counterpart to `isChatsLoading`, plus the whole
        // `queryErrors` map. Both exist because every chat-surface empty state
        // ("No chats yet", "No lorebooks available", "No locations") used to be
        // reachable from a failed fetch — `useChatWorkspaceData` destructured
        // `data` with a `= []` default and no `isError`, so the consumer could
        // not tell "none" from "could not ask".
        isChatsError,
        chatsError,
        refetchChats,
        queryErrors,
        isChatsLoading,
        isGeneratingReply,
        isGeneratingScene,
        isGeneratingTitle,
        isUploading,
        lastLoadedPageFull,
        linkedCharacter,
        listContainerRef,
        listItems,
        loadOlderMessages,
        location,
        lorebooks,
        message,
        messagePageCount,
        messageSearch,
        messages,
        messagesEndRef,
        messagesData,
        mobileTab,
        narrateMode,
        narrateMutation,
        navigate,
        onEditCharacter: setEditingCharacter,
        onEditLocation: openLocationModal,
        onEditLorebook: openLorebookModal,
        openLocationModal,
        openLorebookModal,
        patchCharacterMutation,
        pendingAttachment,
        pinMessageMutation,
        queryClient,
        regenerateMutation,
        renameChatMutation,
        renameValue,
        renamingChatId,
        rollbackMutation,
        rowVirtualizer,
        runLLMJob,
        sceneJobId,
        sceneJobIdRef,
        sceneTab,
        searchResults,
        selectedLorebooks,
        sendMessageMutation,
        setActiveBranch,
        setActiveChatId,
        selectChat,
        setActiveCommand,
        setAgenticMode,
        setAvatarModalSrc,
        setChatOffset,
        setChatSearchQuery,
        setChatsCollapsed,
        setContextCollapsed,
        setGreetingModal,
        setIsGeneratingScene,
        setIsGeneratingTitle,
        setIsUploading,
        setMessage,
        setMessagePageCount,
        setMessageSearch,
        setMobileTab,
        setNarrateMode,
        setPendingAttachment,
        setRenameValue,
        setRenamingChatId,
        setSceneJobId,
        setSceneTab,
        setEditingCharacter,
        setShowCharacterDetails,
        setShowMoreTools,
        setShowNewChatModal,
        setShowScenesModal,
        setSuggestJobId,
        setTargetCharacterId,
        setTimelineVisible,
        showCharacterDetails,
        showLorebookModal,
        showLocationModal,
        showMoreTools,
        showNewChatModal,
        showScenesModal,
        startRename,
        subscribe,
        suggestJobId,
        suggestJobIdRef,
        suggestReplyMutation,
        suggestSafetyTimerRef,
        swipeMessageMutation,
        systemPromptData,
        targetCharacterId,
        textareaRef,
        timelineVisible,
        titlePollCancelledRef,
        triggerAutoTitle,
        turnDirective,
        setTurnDirective,
        updateChatMutation,
        urlChatId,
        voices,
        worlds
    }), [
        CHAT_PAGE_SIZE, MAX_MESSAGE_PAGES, MESSAGE_PAGE_SIZE,
        activeBranch, activeChat, activeChatId, activeChatList,
        activeCommand,
        agenticMode, availableModels, avatarModalSrc,
        canSend, characters, chatCollection, personas,
        chatImages, chatJobs, chatOffset, chatSearchQuery,
        chats, chatsCollapsed, collectionsList,
        confirm, confirmCreateChat, closeLocationModal, closeLorebookModal,
        contextCollapsed,
        createChatMutation, defaultLlmConfig,
        deleteChatMutation, deleteMessageMutation, editMessageMutation,
        editingCharacter, editingLocation, editingLorebook,
        emptyLorebooks, fileInputRef, finishRename,
        generateSceneMutation, generateSwipeMutation,
        greetingModal, handleAttachmentChange, handleAvatarClick, handleCancelStreaming,
        handleChatUpdate, handleCreateChat, handleDeleteChat,
        handleDeleteMessage, handleEditMessage, handleExportChat,
        handleExportChatJsonl, handleExportToStory, exportToStoryMutation, handleImportChatFile,
        isImportingChat, handleGenerateScene, handleGenerateSwipe,
        handleGenerateTTS, handleIllustrate, handleImpersonate,
        handleKeyDown, handleMessageIllustrate, handlePinMessage,
        handleRegenerate, handleRollback, handleSaveCharacter,
        handleSaveImageToCollection,
        handleSendMessage, handleSuggestClick, handleSwipe,
        handleTextChange, hasCreatedChatRef, hasMoreChats,
        hasMoreMessages, illustrateMutation, impersonateMutation,
        // With the rest of the error surface — see the note at the publish site.
        isChatsError, chatsError, refetchChats, queryErrors,
        isChatsLoading, isGeneratingReply, isGeneratingScene, isGeneratingTitle,
        isUploading, lastLoadedPageFull, linkedCharacter,
        listContainerRef, listItems, loadOlderMessages,
        location, lorebooks, message, messagePageCount,
        messageSearch, messages, messagesEndRef, messagesData,
        mobileTab, narrateMode, narrateMutation, navigate,
        openLocationModal, openLorebookModal,
        patchCharacterMutation, pendingAttachment, pinMessageMutation,
        queryClient, regenerateMutation, renameChatMutation,
        renameValue, renamingChatId, rollbackMutation, rowVirtualizer,
        runLLMJob, sceneJobId, sceneJobIdRef, sceneTab,
        searchResults, selectedLorebooks, sendMessageMutation,
        setActiveBranch, setActiveChatId, setActiveCommand,
        setAgenticMode, setAvatarModalSrc, setChatOffset,
        setChatSearchQuery, setChatsCollapsed, setContextCollapsed,
        setGreetingModal, setIsGeneratingScene, setIsGeneratingTitle,
        setIsUploading, setMessage, setMessagePageCount, setMessageSearch,
        setMobileTab, setNarrateMode, setPendingAttachment,
        setRenameValue, setRenamingChatId, setSceneJobId,
        setEditingCharacter, setSceneTab, setShowCharacterDetails,
        setShowMoreTools,
        setShowNewChatModal, setShowScenesModal, setSuggestJobId,
        setTargetCharacterId, setTimelineVisible,
        showCharacterDetails, showLorebookModal, showLocationModal,
        showMoreTools, showNewChatModal,
        showScenesModal, startRename, subscribe, suggestJobId,
        suggestJobIdRef, suggestReplyMutation, suggestSafetyTimerRef,
        selectChat, swipeMessageMutation, systemPromptData, targetCharacterId,
        textareaRef, timelineVisible, titlePollCancelledRef,
        triggerAutoTitle, turnDirective, setTurnDirective, updateChatMutation, urlChatId, voices, worlds
    ]);

    return (
        <ChatWorkspaceContext.Provider value={contextValue}>
            {children}
        </ChatWorkspaceContext.Provider>
    );
}

export const useChatWorkspace = () => {
    const context = useContext(ChatWorkspaceContext);
    if (!context) {
        if (import.meta.env?.DEV) {
            console.warn("useChatWorkspace called outside ChatWorkspaceProvider; returning fallback context.");
        }
        return {};
    }
    return context;
};
