/* eslint-disable react-refresh/only-export-components */
import React, { createContext, useContext, useState, useEffect, useRef, useCallback, useMemo } from 'react';
import toast from 'react-hot-toast';
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useVirtualizer } from '@tanstack/react-virtual';
import {
    useMessages, useChats, useSendMessage, useChat,
    useCreateChat, useDeleteChat, useLorebooks, useCharacters, usePersonas,
    useRenameChat, useUpdateChat, useSuggestReply,
    useLLMAvailableModels, useLLMDefaultProvider, useChatSystemPrompt,
    useCharacterCollection, useEditMessage, useRollbackChat,
    useRegenerateReply, useChatJobs, usePatchCharacter,
    useImpersonateMessage, usePinMessage, useSwipeMessage, useGenerateSwipe, useChatImages,
    useIllustrateChat, useGenerateScene, useNarrateMessage, useDeleteMessage,
    useSearchChats, useExportChatJsonl, useImportChat
} from '../hooks/useWorldVault';
import { useVoices } from '../hooks/useVoices';
import { useLLMJobResult } from '../hooks/useLLMJobResult';
import { useCollections } from '../hooks/useCollections';
import { filesApi } from '../api/files';
import { addImagesToCollection } from '../api/collectionsApi';
import { useWorldVaultStore } from '../store/worldVaultStore';
import { useConfirmation } from '../store/confirmationStore';
import { useSettings } from '../store/settingsStore';
import { useWebSocket, EventTypes } from '../api/websocket';
import { useChatStreaming } from '../hooks/useChatStreaming';
import { setStreamingJob, useActiveChatStreams } from '../hooks/useStreamingJobs';
import { COMMANDS } from '../components/chat/chatCommands';

const ChatWorkspaceContext = createContext(null);

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
    const textareaRef = useRef(null);
    const location = useLocation();
    const navigate = useNavigate();
    const { chatId: urlChatId } = useParams();
    const [searchParams, setSearchParams] = useSearchParams();

    const settings = useSettings();
    
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
        if (activeChatId && activeChatId !== urlChatId) {
            navigate(`/chat/${activeChatId}`, { replace: true });
        } else if (!activeChatId && urlChatId) {
            navigate('/chat', { replace: true });
        }
    }, [activeChatId]); // eslint-disable-line react-hooks/exhaustive-deps

    const activeStreamEntries = useActiveChatStreams(activeChatId);
    const activeStreams = useMemo(
        () => activeStreamEntries
            .filter(item => item.jobData?.status === 'running')
            .map(item => ({ _key: `stream-${item.jobId}`, jobId: item.jobId, jobData: item.jobData })),
        [activeStreamEntries]
    );
    
    const suggestReplyMutation = useSuggestReply();
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
    
    const [activeCommand, setActiveCommand] = useState(null);
    const [targetCharacterId, setTargetCharacterId] = useState('');
    
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
    const { data: chats, isLoading: isChatsLoading } = useChats({ limit: CHAT_PAGE_SIZE, offset: chatOffset });
    const { data: searchResults } = useSearchChats(chatSearchQuery);
    const activeChatList = chatSearchQuery.trim() ? (searchResults || []) : chats;
    const hasMoreChats = chats?.length === CHAT_PAGE_SIZE && !chatSearchQuery.trim();

    // Message pagination: page 0 is the newest 100 messages (ascending order,
    // newest last). Older pages are appended above them on demand.
    const MESSAGE_PAGE_SIZE = 100;
    const MAX_MESSAGE_PAGES = 5;
    const [messagePageCount, setMessagePageCount] = useState(1);
    const [messageSearch, setMessageSearch] = useState('');

    const { data: messagesData = [] } = useMessages(
        activeChatId,
        { limit: messagePageCount * MESSAGE_PAGE_SIZE, offset: 0, branchId: activeBranch, search: messageSearch || null }
    );
    
    const messages = messagesData;
    const lastLoadedPageFull = messagesData.length === messagePageCount * MESSAGE_PAGE_SIZE;
    const hasMoreMessages = messagePageCount < MAX_MESSAGE_PAGES && lastLoadedPageFull;
    const loadOlderMessages = () => setMessagePageCount(c => Math.min(c + 1, MAX_MESSAGE_PAGES));

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
    const collectionsList = useMemo(
        () => Object.values(collectionsMap).sort((a, b) => (a.name || '').localeCompare(b.name || '')),
        [collectionsMap]
    );

    // Combine messages + active streaming jobs for virtualized list.
    // `activeStreams` is sourced from the React-Query-backed hook above.
    const listItems = useMemo(
        () => [
            ...messages.map(msg => ({ _key: msg.id || `msg-${messages.indexOf(msg)}`, item: msg })),
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

    // Use activeChat's lorebooks instead of the store's global state
    const emptyLorebooks = useMemo(() => [], []);
    const selectedLorebooks = activeChat?.active_lorebook_ids || emptyLorebooks;

    const sendMessageMutation = useSendMessage();
    const createChatMutation = useCreateChat();
    const exportJsonlMutation = useExportChatJsonl();
    const importChatMutation = useImportChat();
    const deleteChatMutation = useDeleteChat();
    const renameChatMutation = useRenameChat();
    const updateChatMutation = useUpdateChat();
    const editMessageMutation = useEditMessage();
    const rollbackMutation = useRollbackChat();
    const regenerateMutation = useRegenerateReply();
    const patchCharacterMutation = usePatchCharacter();
    const deleteMessageMutation = useDeleteMessage();
    const impersonateMutation = useImpersonateMessage();
    const pinMessageMutation = usePinMessage();
    const swipeMessageMutation = useSwipeMessage();
    const generateSwipeMutation = useGenerateSwipe();
    const narrateMutation = useNarrateMessage();
    const { data: voices = [] } = useVoices();
    const illustrateMutation = useIllustrateChat();
    const generateSceneMutation = useGenerateScene();
    const { data: chatJobs = [] } = useChatJobs(activeChatId);

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
                        window.history.replaceState({}, document.title);
                    }
                });
            } else {
                createChatMutation.mutate(
                    { name: 'New Chat', character_id: characterId },
                    {
                        onSuccess: (chat) => {
                            setActiveChatId(chat.id);
                            window.history.replaceState({}, document.title);
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
        // During streaming, use instant (non-smooth) scrolling — smooth
        // scrolling per token triggers repeated layout + animation on mobile.
        const hasStreaming = activeStreamEntries.length > 0;
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

        setMessage('');
        const attachmentFilename = pendingAttachment?.filename || null;
        setPendingAttachment(null);
        
        const currentCommand = activeCommand;
        setActiveCommand(null);
        
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
                } catch { toast.error("Failed to update time"); }
                return;
            } else if (cmd === '/location') {
                if (!arg) { toast.error("Provide a location"); return; }
                try {
                    await updateChatMutation.mutateAsync({ chatId: chatIdToUse, story_location: arg });
                } catch { toast.error("Failed to update location"); }
                return;
            } else if (cmd === '/me' || cmd === '/action') {
                msgContent = `*${arg}*`;
                if (!arg && !attachmentFilename) { toast.error("Provide action text"); return; }
            } else if (cmd === '/suggest') {
                try {
                    const res = await suggestReplyMutation.mutateAsync({ chatId: chatIdToUse, draft: arg || undefined });
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
                    generator_checkpoint: settings.generator?.defaultCheckpoint || null,
                    no_reply: noReply
                }
            });
            if (res.job_id) {
                setStreamingJob(queryClient, res.job_id, { text: '', status: 'running', chatId: chatIdToUse });
            }
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', chatIdToUse] });
        } catch {
            toast.error('Failed to send message');
        }
    }, [message, pendingAttachment, activeChatId, selectedLorebooks, agenticMode, narrateMode, createChatMutation, sendMessageMutation, queryClient, setActiveChatId, settings, updateChatMutation, suggestReplyMutation, activeCommand, targetCharacterId]);

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

    const handleTextChange = (e) => {
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
    };

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

    const canSend = (message.trim() || pendingAttachment || activeCommand?.noArgs) && !sendMessageMutation.isPending;

    const handleGenerateScene = async () => {
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
    };

    const handleIllustrate = async () => {
        if (!activeChatId || illustrateMutation.isPending) return;
        const prompt = message.trim();
        try {
            await illustrateMutation.mutateAsync({ chatId: activeChatId, imagePrompt: prompt });
            if (prompt) setMessage('');
            toast.success('Illustration queued...', { icon: '🖼️' });
        } catch {
            toast.error('Failed to start illustration');
        }
    };

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

    const triggerAutoTitle = async () => {
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
    };

    const handleCreateChat = () => {
        setShowNewChatModal(true);
    };

    const confirmCreateChat = (config) => {
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
    };

    const handleAttachmentChange = async (e) => {
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
    };

    const handleDeleteChat = async (chat) => {
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
    };

    const startRename = (chat) => { setRenamingChatId(chat.id); setRenameValue(chat.name || ''); };
    const finishRename = async () => {
        if (renamingChatId && renameValue.trim()) {
            try {
                await renameChatMutation.mutateAsync({ chatId: renamingChatId, name: renameValue.trim() });
                toast.success('Chat renamed');
            } catch { toast.error('Failed to rename'); }
        }
        setRenamingChatId(null);
    };

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

    const handleExportChatJsonl = async () => {
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
    };

    const isImportingChat = importChatMutation.isPending;
    const handleImportChatFile = async (file) => {
        if (!file) return;
        const formData = new FormData();
        formData.append('file', file);
        try {
            const chat = await importChatMutation.mutateAsync(formData);
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats'] });
            setActiveChatId(chat.id);
            toast.success(`Imported "${chat.name}"`);
        } catch (err) {
            toast.error(err.message || 'Failed to import chat');
        }
    };

    const handleExportChat = () => {
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
            // Skip world-state UI dividers in the export
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
    };

    const linkedCharacter = characters.find(c => c.id === activeChat?.character_id);

    const contextValue = {
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
        settings,
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
    };

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
