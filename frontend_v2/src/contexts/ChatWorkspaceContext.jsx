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
import { addImagesToCollection } from '../api/collectionsApi';
import { useWorldVaultStore } from '../store/worldVaultStore';
import { useConfirmation } from '../store/confirmationStore';
import useSettingsStore from '../store/settingsStore';
import { useWebSocket, EventTypes } from '../api/websocket';
import { useDebounce } from '../hooks/useDebounce';
import { useChatStreaming } from '../hooks/useChatStreaming';
import { CHAT_LIST_KEY } from '../hooks/useChats';
import { setStreamingJob } from '../hooks/useStreamingJobs';
import { COMMANDS } from '../components/chat/chatCommands';

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
    const [pendingAttachment, setPendingAttachment] = useState(null);
    const [isUploading, setIsUploading] = useState(false);
    const [agenticMode, setAgenticMode] = useState(true);
    const [narrateMode, setNarrateMode] = useState(false);
    const [isGeneratingTitle, setIsGeneratingTitle] = useState(false);
    const [greetingModal, setGreetingModal] = useState(null);
    const [showNewChatModal, setShowNewChatModal] = useState(false);
    const [showCharacterDetails, setShowCharacterDetails] = useState(false);
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
        if (urlChatId && activeChatId !== urlChatId) {
            setActiveChatId(urlChatId);
        } else if (!urlChatId && activeChatId) {
            navigate(`/chat/${activeChatId}`, { replace: true });
        }
    }, [activeChatId, urlChatId, navigate, setActiveChatId]);

    const [suggestJobId, setSuggestJobId] = useState(null);
    const suggestJobIdRef = useRef(null);
    const suggestSafetyTimerRef = useRef(null);
    const titlePollCancelledRef = useRef(false);

    useEffect(() => {
        return () => {
            if (suggestSafetyTimerRef.current) {
                clearTimeout(suggestSafetyTimerRef.current);
                suggestSafetyTimerRef.current = null;
            }
        };
    }, []);

    // Declared before the chat-switch reset below, which closes over all three:
    // the effect only ran because the callback executes after the body
    // finishes, so hoisting the declarations is what keeps it from becoming a
    // TDZ ReferenceError the day anyone reorders this block.
    const [activeCommand, setActiveCommand] = useState(null);
    const [targetCharacterId, setTargetCharacterId] = useState('');

    const previousChatIdRef = useRef(activeChatId);
    useEffect(() => {
        if (previousChatIdRef.current && previousChatIdRef.current !== activeChatId) {
            setMessage('');
            setPendingAttachment(null);
            setActiveCommand(null);
            setTargetCharacterId('');
            setMessageSearch('');
            setActiveBranchState(null);
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
        chats, isChatsLoading, searchResults, messagesData, activeChat, lorebooks, characters,
        personas, availableModels, defaultLlmConfig, systemPromptData, chatCollection, chatImages,
        collectionsMap, voices, chatJobs, activeStreamEntries, activeStreams,
    } = cwData;
    const cwMutations = useChatWorkspaceMutations();
    const {
        sendMessageMutation: rawSendMessageMutation, createChatMutation: rawCreateChatMutation,
        exportJsonlMutation: rawExportJsonlMutation, importChatMutation: rawImportChatMutation,
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

    const activeChatList = useMemo(
        () => debouncedChatSearchQuery.trim() ? (searchResults || []) : chats,
        [debouncedChatSearchQuery, searchResults, chats]
    );
    const hasMoreChats = useMemo(
        () => chats?.length === CHAT_PAGE_SIZE && !debouncedChatSearchQuery.trim(),
        [chats, debouncedChatSearchQuery]
    );

    const messages = messagesData;
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
            ...messages.map((msg, i) => ({ _key: msg.id || `msg-${i}`, item: msg })),
            ...activeStreams,
        ],
        [messages, activeStreams]
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
                        setActiveChatId(chat.id);
                    }
                });
            } else {
                createChatMutation.mutate(
                    { name: 'New Chat', character_id: characterId },
                    {
                        onSuccess: (chat) => {
                            setActiveChatId(chat.id);
                        },
                        onError: () => { hasCreatedChatRef.current = false; }
                    }
                );
            }
        }
    }, [location.state?.characterId, characters, activeChatId, createChatMutation, setActiveChatId]);

    useEffect(() => {
        if (chats?.length > 0 && !activeChatId) {
            setActiveChatId(chats[0].id);
        }
    }, [chats, activeChatId, setActiveChatId]);

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
                setActiveChatId(newChat.id);
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

        try {
            const res = await sendMessageMutation.mutateAsync({
                chatId: chatIdToUse,
                message: { 
                    role: role, 
                    content: msgContent, 
                    lorebook_ids: selectedLorebooks, 
                    image_path: attachmentFilename, 
                    target_character_id: targetCharacterId || null,
                    agentic: agenticMode,
                    narrate: narrateMode,
                    generator_checkpoint: generatorCheckpoint || null,
                    no_reply: noReply
                }
                });
            setMessage('');
            setPendingAttachment(null);
            setActiveCommand(null);
            if (res.job_id) {

                setStreamingJob(queryClient, res.job_id, { text: '', status: 'running', chatId: chatIdToUse });
            }
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', chatIdToUse] });
        } catch {
            toast.error('Failed to send message');
        }
    }, [message, pendingAttachment, activeChatId, selectedLorebooks, agenticMode, narrateMode, createChatMutation, sendMessageMutation, queryClient, setActiveChatId, generatorCheckpoint, updateChatMutation, suggestReplyMutation, activeCommand, targetCharacterId]);

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

        const canSend = useMemo(
            () => !!(message.trim() || pendingAttachment || activeCommand?.noArgs) && !sendMessageMutation.isPending,
            [message, pendingAttachment, activeCommand, sendMessageMutation]
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
                setStreamingJob(queryClient, data.job_id, { text: 'Generating scene image...', status: 'running', chatId: activeChatId, type: 'roleplay', taskType: 'llm' });
            }
        } catch {
            toast.error('Failed to generate scene');
            setIsGeneratingScene(false);
        }
    }, [activeChatId, generateSceneMutation, queryClient]);

    const handleIllustrate = useCallback(async () => {
        if (!activeChatId || illustrateMutation.isPending) return;
        const prompt = message.trim();
        try {
            await illustrateMutation.mutateAsync({ chatId: activeChatId, imagePrompt: prompt });
            if (prompt) setMessage('');
            toast.success('Illustration queued...', { icon: '🖼️' });
        } catch {
            toast.error('Failed to start illustration');
        }
    }, [activeChatId, message, illustrateMutation]);

    const handleSaveImageToCollection = useCallback(async (collectionId, path) => {
        if (!collectionId || !path) return;
        try {
            await addImagesToCollection(collectionId, [path]);
            queryClient.invalidateQueries({ queryKey: ['collections'] });
            if (activeChat?.character_id) {
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', activeChat.character_id, 'collection'] });
            }
            toast.success('Image saved to collection');
        } catch {
            toast.error('Failed to save image');
        }
    }, [queryClient, activeChat?.character_id]);

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
        const { chatName, characterId, personaName, personaId, storyTime, storyLocation, selectedLorebooks: newSelectedLorebooks } = config;

        const character = characterId ? characters.find(c => c.id === characterId) : null;
        const hasMultipleGreetings = character && (character.alternate_greetings?.length > 0);

        const payload = {
            name: chatName,
            character_id: characterId,
            persona_name: personaName,
            persona_id: personaId || null,
            story_time: storyTime,
            story_location: storyLocation,
            active_lorebook_ids: newSelectedLorebooks
        };

        if (hasMultipleGreetings) {
            setGreetingModal({
                character,
                onCreate: async (selectedGreeting) => {
                    setGreetingModal(null);
                    const chat = await createChatMutation.mutateAsync({ 
                        ...payload,
                        override_greeting: selectedGreeting 
                    });
                    setActiveChatId(chat.id);
                    setMobileTab('chat');
                    toast.success('New chat created');
                }
            });
        } else {
            createChatMutation.mutate(
                payload,
                {
                    onSuccess: (chat) => {
                        setActiveChatId(chat.id);
                        setMobileTab('chat');
                        toast.success('New chat created');
                    },
                    onError: () => toast.error('Failed to create chat')
                }
            );
        }
    }, [createChatMutation, characters, setActiveChatId, setMobileTab, setGreetingModal, setShowNewChatModal]);

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
                const remaining = chats?.filter(c => c.id !== chat.id);
                setActiveChatId(remaining?.[0]?.id || null);
            }
            toast.success('Chat deleted');
        } catch {
            toast.error('Failed to delete chat');
        }
    }, [activeChatId, chats, confirm, deleteChatMutation, setActiveChatId]);

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
        try {
            const res = await regenerateMutation.mutateAsync({ chatId: activeChatId, messageId: msgId });
            if (res?.job_id) setStreamingJob(queryClient, res.job_id, { text: '', status: 'running', chatId: activeChatId, type: 'llm' });
        } catch { toast.error('Failed to regenerate'); }
    }, [activeChatId, regenerateMutation, queryClient]);

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
            const res = await generateSwipeMutation.mutateAsync({ chatId: activeChatId, msgId });
            if (res?.job_id) {
                setStreamingJob(queryClient, res.job_id, { text: '', status: 'running', chatId: activeChatId, type: 'llm' });
                toast('Generating alternate reply...', { icon: '✨' });
            }
        } catch { toast.error('Failed to generate swipe'); }
    }, [activeChatId, generateSwipeMutation, queryClient]);

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
                imagePrompt: msg?.content || ''
            });
            if (res?.job_id) {
                setStreamingJob(queryClient, res.job_id, { text: '', status: 'running', chatId: activeChatId, type: 'image' });
                toast.success('Illustration started', { icon: '✨' });
            }
        } catch { toast.error('Failed to start illustration'); }
    }, [activeChatId, messages, illustrateMutation, queryClient]);

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
            setActiveChatId(chat.id);
            toast.success(`Imported "${chat.name}"`);
        } catch (err) {
            toast.error(err.message || 'Failed to import chat');
        }
    }, [importChatMutation, queryClient, setActiveChatId]);

    const linkedCharacter = characters.find(c => c.id === activeChat?.character_id);

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
        activeStreamEntries,
        activeStreams,
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
        contextCollapsed,
        createChatMutation,
        defaultLlmConfig,
        deleteChatMutation,
        deleteMessageMutation,
        editMessageMutation,
        emptyLorebooks,
        fileInputRef,
        finishRename,
        generateSceneMutation,
        generateSwipeMutation,
        greetingModal,
        handleAttachmentChange,
        handleAvatarClick,
        handleChatUpdate,
        handleCreateChat,
        handleDeleteChat,
        handleDeleteMessage,
        handleEditMessage,
        handleExportChat,
        handleExportChatJsonl,
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
        isChatsLoading,
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
        setShowCharacterDetails,
        setShowMoreTools,
        setShowNewChatModal,
        setShowScenesModal,
        setSuggestJobId,
        setTargetCharacterId,
        setTimelineVisible,
        showCharacterDetails,
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
        updateChatMutation,
        urlChatId,
        voices
    }), [
        CHAT_PAGE_SIZE, MAX_MESSAGE_PAGES, MESSAGE_PAGE_SIZE,
        activeBranch, activeChat, activeChatId, activeChatList,
        activeCommand, activeStreamEntries, activeStreams,
        agenticMode, availableModels, avatarModalSrc,
        canSend, characters, chatCollection, personas,
        chatImages, chatJobs, chatOffset, chatSearchQuery,
        chats, chatsCollapsed, collectionsList,
        confirm, confirmCreateChat, contextCollapsed,
        createChatMutation, defaultLlmConfig,
        deleteChatMutation, deleteMessageMutation, editMessageMutation,
        emptyLorebooks, fileInputRef, finishRename,
        generateSceneMutation, generateSwipeMutation,
        greetingModal, handleAttachmentChange, handleAvatarClick,
        handleChatUpdate, handleCreateChat, handleDeleteChat,
        handleDeleteMessage, handleEditMessage, handleExportChat,
        handleExportChatJsonl, handleImportChatFile,
        isImportingChat, handleGenerateScene, handleGenerateSwipe,
        handleGenerateTTS, handleIllustrate, handleImpersonate,
        handleKeyDown, handleMessageIllustrate, handlePinMessage,
        handleRegenerate, handleRollback, handleSaveImageToCollection,
        handleSendMessage, handleSuggestClick, handleSwipe,
        handleTextChange, hasCreatedChatRef, hasMoreChats,
        hasMoreMessages, illustrateMutation, impersonateMutation,
        isChatsLoading, isGeneratingScene, isGeneratingTitle,
        isUploading, lastLoadedPageFull, linkedCharacter,
        listContainerRef, listItems, loadOlderMessages,
        location, lorebooks, message, messagePageCount,
        messageSearch, messages, messagesEndRef, messagesData,
        mobileTab, narrateMode, narrateMutation, navigate,
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
        setSceneTab, setShowCharacterDetails, setShowMoreTools,
        setShowNewChatModal, setShowScenesModal, setSuggestJobId,
        setTargetCharacterId, setTimelineVisible,
        showCharacterDetails, showMoreTools, showNewChatModal,
        showScenesModal, startRename, subscribe, suggestJobId,
        suggestJobIdRef, suggestReplyMutation, suggestSafetyTimerRef,
        swipeMessageMutation, systemPromptData, targetCharacterId,
        textareaRef, timelineVisible, titlePollCancelledRef,
        triggerAutoTitle, updateChatMutation, urlChatId, voices
    ]);

    return (
        <ChatWorkspaceContext.Provider value={contextValue}>
            {children}
        </ChatWorkspaceContext.Provider>
    );
}

export const useChatWorkspace = () => {
    const context = useContext(ChatWorkspaceContext);
    if (!context) throw new Error("useChatWorkspace must be used within ChatWorkspaceProvider");
    return context;
};
