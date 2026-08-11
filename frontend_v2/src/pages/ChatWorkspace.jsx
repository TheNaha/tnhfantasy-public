import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
    MessageSquare, Send, Image as ImageIcon, Settings,
    PanelRightClose, PanelRightOpen, PanelLeftClose, PanelLeftOpen, Paperclip, Sparkles,
    Plus, Loader2, Trash2, Edit3, BookOpen, Wand2,
    X, Clock, MapPin,
    Activity, Download, Ghost,
    MoreHorizontal, Palette
} from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import {
    useMessages, useChats, useSendMessage, useChat,
    useCreateChat, useDeleteChat, useLorebooks, useCharacters,
    useRenameChat, useUpdateChat, getAvatarUrl, useSuggestReply,
    useLLMAvailableModels, useLLMDefaultProvider, useChatSystemPrompt,
    useCharacterCollection, useEditMessage, useRollbackChat,
    useRegenerateReply, useChatJobs, usePatchCharacter,
    useImpersonateMessage, usePinMessage, useSwipeMessage, useChatImages,
    useIllustrateChat, useGenerateScene
} from '../hooks/useWorldVault';
import { useLLMJobResult } from '../hooks/useLLMJobResult';
import { useVirtualizer } from '@tanstack/react-virtual';
import { filesApi } from '../api/files';
import { useCollections } from '../hooks/useCollections';
import { addImagesToCollection } from '../api/collectionsApi';
import { useWorldVaultStore } from '../store/worldVaultStore';
import { useWebSocket, EventTypes } from '../api/websocket';
import {
    useActiveChatStreams,
    setStreamingJob,
    clearStreamingJob,
    getStreamingJob,
} from '../hooks/useStreamingJobs';
import { useQueryClient } from '@tanstack/react-query';
import { useConfirmation } from '../store/confirmationStore';
import { useSettings } from '../store/settingsStore';
import SceneGallery from '../components/SceneGallery';
import BottomTabBar from '../components/BottomTabBar';
import TavernMessage from '../components/chat/TavernMessage';
import MessageItem from '../components/chat/MessageItem';
import NewChatModal from '../components/chat/NewChatModal';
import GreetingPickerModal from '../components/chat/GreetingPickerModal';
import CharacterDetailsModal from '../components/chat/CharacterDetailsModal';
import ChatContextPanel from '../components/chat/ChatContextPanel';
import CommandPalette from '../components/chat/CommandPalette';
import { COMMANDS } from '../components/chat/chatCommands';
import StreamingInput from '../components/chat/StreamingInput';


export default function ChatWorkspace() {
    const [mobileTab, setMobileTab] = useState('chat'); // 'chats', 'chat', 'context'
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

    const settings = useSettings();
    
    const queryClient = useQueryClient();
    const activeChatId = useWorldVaultStore(state => state.activeChatId);
    const setActiveChatId = useWorldVaultStore(state => state.setActiveChat);

    // Deep-linking: /chat/:chatId is the source of truth for the active chat.
    // URL change -> store, store change -> URL. replace() keeps back/forward
    // history clean when hopping between chats.
    useEffect(() => {
        if (urlChatId && urlChatId !== activeChatId) {
            setActiveChatId(urlChatId);
        }
    }, [urlChatId]); // eslint-disable-line react-hooks/exhaustive-deps

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
    const { data: chats, isLoading: isChatsLoading } = useChats({ limit: CHAT_PAGE_SIZE, offset: chatOffset });
    const hasMoreChats = chats?.length === CHAT_PAGE_SIZE;

    // Message pagination: page 0 is the newest 100 messages (ascending order,
    // newest last). Older pages are appended above them on demand.
    const MESSAGE_PAGE_SIZE = 100;
    const MAX_MESSAGE_PAGES = 5;
    const [messagePageCount, setMessagePageCount] = useState(1);
    
    const { data: messagesData = [] } = useMessages(
        activeChatId,
        { limit: messagePageCount * MESSAGE_PAGE_SIZE, offset: 0 }
    );
    
    const messages = messagesData;
    const lastLoadedPageFull = messagesData.length === messagePageCount * MESSAGE_PAGE_SIZE;
    const hasMoreMessages = messagePageCount < MAX_MESSAGE_PAGES && lastLoadedPageFull;
    const loadOlderMessages = () => setMessagePageCount(c => Math.min(c + 1, MAX_MESSAGE_PAGES));

    const { data: activeChat } = useChat(activeChatId);
    const { data: lorebooks = [] } = useLorebooks();
    const { data: characters = [] } = useCharacters();
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
    const deleteChatMutation = useDeleteChat();
    const renameChatMutation = useRenameChat();
    const updateChatMutation = useUpdateChat();
    const editMessageMutation = useEditMessage();
    const rollbackMutation = useRollbackChat();
    const regenerateMutation = useRegenerateReply();
    const patchCharacterMutation = usePatchCharacter();
    const impersonateMutation = useImpersonateMessage();
    const pinMessageMutation = usePinMessage();
    const swipeMessageMutation = useSwipeMessage();
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

    useEffect(() => {
        // Helper: extract job data from the WS envelope.
        // Backend emits: { type, data: { job: {...} }, timestamp, sequence_number }
        const getJob = (event) => event?.data?.job || {};

        // Throttle streaming updates to ~10Hz. The backend streams one
        // JOB_PROGRESS per token and each payload carries the FULL accumulated
        // text, so keeping only the latest per job is lossless while avoiding
        // a full page re-render per token (the root cause of hot mobile devices).
        const pendingStream = new Map();
        let flushTimer = null;

        const applyStreamUpdate = (job) => {
            const streamText = job.text ?? job.message ?? null;
            const meta = job.metadata_ ?? job.metadata ?? {};
            const eventId = job.id ?? null;

            // is_suggestion: check job_id ref first (more reliable), then metadata flag
            const isSuggestion = eventId === suggestJobIdRef.current || !!meta.is_suggestion;
            if (isSuggestion) {
                if (streamText) setMessage(streamText);
                return;
            }

            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;
            if (streamText && eventChatId) {
                setStreamingJob(queryClient, eventId, {
                    text: streamText,
                    status: 'running',
                    chatId: eventChatId,
                    type: meta.workspace,
                    taskType: job.task_type ?? null,
                    progress: job.overall_progress ?? job.progress ?? null
                });
            }
        };

        const throttleProgress = (job) => {
            const eventId = job.id ?? null;
            if (!eventId) { applyStreamUpdate(job); return; }
            pendingStream.set(eventId, job);
            if (flushTimer) return;
            flushTimer = setTimeout(() => {
                flushTimer = null;
                for (const [, pendingJob] of pendingStream) applyStreamUpdate(pendingJob);
                pendingStream.clear();
            }, 100);
        };

        const unsubProgress = subscribe(EventTypes.JOB_PROGRESS, (event) => {
            throttleProgress(getJob(event));
        });

        const unsubCompleted = subscribe(EventTypes.JOB_COMPLETED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            const eventId = job.id ?? null;

            // Drop any buffered progress chunks for this job — a late flush
            // would resurrect the streaming bubble after it was cleared.
            if (eventId) pendingStream.delete(eventId);

            const isSuggestion = eventId === suggestJobIdRef.current || !!meta.is_suggestion;
            if (isSuggestion) {
                // Grab final text from outputs if streaming missed it
                const outputText = job.outputs?.[0]?.content ?? null;
                if (outputText) setMessage(outputText);
                setSuggestJobId(null);
                return;
            }

            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;

            if (eventId) clearStreamingJob(queryClient, eventId, eventChatId);

            if (eventChatId) {
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', eventChatId] });
                // Story time/location may have changed via update_world_state — refresh chat.
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', eventChatId] });
                if (job.task_type === 'image') {
                    queryClient.invalidateQueries({ queryKey: ['world_vault', 'chat', 'images', eventChatId] });
                }
            }

            if (eventChatId === activeChatId) {
                const jobType = meta.workspace || job.task_type;
                if (jobType === 'image' || meta.image_context) {
                    toast.success('Image generated!', { icon: '🖼️' });
                }
            }

            // Clear scene generation state when the scene job completes
            if (eventId === sceneJobIdRef.current) {
                sceneJobIdRef.current = null;
                setSceneJobId(null);
                setIsGeneratingScene(false);
            }
        });

        const unsubError = subscribe(EventTypes.JOB_FAILED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            const eventId = job.id ?? null;
            if (eventId) pendingStream.delete(eventId);
            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;

            if (eventId === suggestJobIdRef.current) setSuggestJobId(null);
            if (eventId) clearStreamingJob(queryClient, eventId, eventChatId);

            if (eventChatId === activeChatId) {
                toast.error('AI response failed. Please try again.');
            }

            // Clear scene generation state when the scene job fails
            if (eventId === sceneJobIdRef.current) {
                sceneJobIdRef.current = null;
                setSceneJobId(null);
                setIsGeneratingScene(false);
            }
        });

        // JOB_CANCELLED unhandled before: left a stuck 'thinking…' bubble and
        // a permanently disabled Suggest button. Clear the stream state here.
        const unsubCancelled = subscribe(EventTypes.JOB_CANCELLED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            const eventId = job.id ?? null;
            if (eventId) pendingStream.delete(eventId);
            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;

            if (eventId === suggestJobIdRef.current) setSuggestJobId(null);
            if (eventId) clearStreamingJob(queryClient, eventId, eventChatId);

            if (eventChatId === activeChatId) {
                toast('AI response cancelled', { icon: '🛑' });
            }
        });

        return () => {
            if (flushTimer) clearTimeout(flushTimer);
            pendingStream.clear();
            unsubProgress(); unsubCompleted(); unsubError(); unsubCancelled();
        };
    }, [subscribe, activeChatId, queryClient]);

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
        if (!msgContentRaw && !pendingAttachment && !activeCommand?.noArgs) return;

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
    }, [message, pendingAttachment, activeChatId, selectedLorebooks, agenticMode, narrateMode, createChatMutation, sendMessageMutation, queryClient, setActiveChatId, settings, updateChatMutation, suggestReplyMutation, activeCommand]);

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
        const { chatName, characterId, personaName, storyTime, storyLocation, selectedLorebooks: newSelectedLorebooks } = config;
        
        const character = characterId ? characters.find(c => c.id === characterId) : null;
        const hasMultipleGreetings = character && (character.alternate_greetings?.length > 0);

        const payload = { 
            name: chatName, 
            character_id: characterId, 
            persona_name: personaName, 
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

    const renderRow = (item) => {
        if (item.item) {
            const msg = item.item;
            const idx = messages.findIndex(m => (m.id || m._idx) === (msg.id || msg._idx));
            return (
                <MessageItem
                    msg={msg}
                    linkedCharacter={linkedCharacter}
                    activeChat={activeChat}
                    canRegenerate={idx === messages.length - 1}
                    onEdit={handleEditMessage}
                    onRegenerate={handleRegenerate}
                    onRollback={handleRollback}
                    onPin={handlePinMessage}
                    onSwipe={handleSwipe}
                    onAvatarClick={handleAvatarClick}
                />
            );
        }
        const { jobId, jobData } = item;
        if (jobData.taskType === 'image' || jobData.type === 'image') {
            return (
                <div className="self-start w-full max-w-[85%] sm:max-w-md">
                    <div className="text-[10px] text-green-400 ml-1 flex items-center gap-1.5 mb-1">
                        <ImageIcon size={10} /> Generating scene image
                    </div>
                    <div className="rounded-2xl border border-gray-700/40 bg-gray-900/60 p-3 overflow-hidden shadow-inner">
                        <div className="flex gap-3">
                            <div className="w-20 h-20 sm:w-24 sm:h-24 rounded-xl bg-gray-800 animate-pulse shimmer" />
                            <div className="flex-1 space-y-2 py-1">
                                <div className="h-2.5 w-3/4 rounded bg-gray-800 animate-pulse" />
                                <div className="h-2.5 w-1/2 rounded bg-gray-800 animate-pulse" />
                                <div className="h-2.5 w-2/3 rounded bg-gray-800 animate-pulse" />
                                {jobData.progress != null ? (
                                    <div className="pt-2">
                                        <div className="h-1.5 w-full rounded-full bg-gray-800 overflow-hidden">
                                            <div className="h-full bg-gradient-to-r from-green-500 to-emerald-400 rounded-full transition-all" style={{ width: `${jobData.progress}%` }} />
                                        </div>
                                        <div className="text-[10px] text-green-400/80 mt-1 flex items-center gap-1">
                                            <Loader2 size={10} className="animate-spin" />
                                            Rendering {jobData.progress}%
                                        </div>
                                    </div>
                                ) : (
                                    <div className="pt-2 text-[10px] text-purple-400 flex items-center gap-1">
                                        <Wand2 size={10} className="animate-pulse" />
                                        Preparing generation...
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            );
        }
        return (
            <div key={jobId} className="flex gap-2 sm:gap-3 max-w-[90%] sm:max-w-[85%] self-start flex-row">
                <button
                    type="button"
                    onClick={() => linkedCharacter?.avatar_path && handleAvatarClick(getAvatarUrl(linkedCharacter.id))}
                    className={clsx(
                        "w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0 overflow-hidden self-end",
                        linkedCharacter?.avatar_path && "cursor-pointer hover:border-blue-500/50 transition-colors"
                    )}
                >
                    {linkedCharacter?.avatar_path
                        ? <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-full h-full object-cover" />
                        : <MessageSquare className="text-blue-400" size={12} />
                    }
                </button>
                <div className="flex flex-col max-w-full">
                    <div className="text-[10px] mb-1 text-gray-400 flex items-center gap-1.5">
                        <span>{linkedCharacter?.name || 'AI'}</span>
                        <span className="inline-flex items-center gap-0.5 text-blue-400/70">
                            <span className="w-1 h-1 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                            <span className="w-1 h-1 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                            <span className="w-1 h-1 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: '300ms' }} />
                        </span>
                    </div>
                    <div className="px-4 py-3 rounded-2xl rounded-tl-sm text-sm bg-gray-800/50 text-gray-200 border border-gray-700/40 leading-relaxed">
                        {jobData.text ? (
                            <TavernMessage content={jobData.text + '\u25CD'} />
                        ) : (
                            <span className="flex items-center gap-2 text-gray-400 text-sm italic">
                                *{linkedCharacter?.name || 'AI'} is thinking...*
                            </span>
                        )}
                    </div>
                </div>
            </div>
        );
    };

    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col h-full relative overflow-hidden bg-gray-900"
        >
            {/* === THREE-COLUMN ROW (fills remaining height above mobile tab bar) === */}
            <div className="flex flex-1 flex-row min-h-0 overflow-hidden">
            <div className={clsx(
                "flex-col shrink-0 border-b lg:border-r border-white/5 bg-gray-900 flex-1 lg:flex-none overflow-hidden min-w-0",
                "w-full",
                chatsCollapsed ? "lg:w-0 lg:border-r-0" : "lg:w-72",
                mobileTab === 'chats' ? "flex" : "hidden lg:flex"
            )}>
                <div className="h-12 lg:h-16 flex items-center justify-between px-4 border-b border-white/5 shrink-0">
                    <h3 className="font-semibold text-gray-200 tracking-wide">Chats</h3>
                    <button
                        onClick={() => handleCreateChat()}
                        className="p-1.5 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                        title="New chat"
                    >
                        <Plus size={18} />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-2 space-y-1 custom-scrollbar">
                    {isChatsLoading ? (
                        <div className="flex justify-center p-4"><Loader2 className="animate-spin text-gray-500" size={20} /></div>
                    ) : chats?.length === 0 ? (
                        <div className="text-center py-8 text-gray-600 text-sm px-4">
                            <MessageSquare size={28} className="mx-auto mb-2 opacity-40" />
                            <p>No chats yet</p>
                            <p className="text-xs mt-1">Click + to create one</p>
                        </div>
                    ) : chats?.map(chat => (
                        <div key={chat.id} className="relative group">
                            {renamingChatId === chat.id ? (
                                <div className="flex items-center gap-1 px-1">
                                    <input
                                        autoFocus
                                        value={renameValue}
                                        onChange={e => setRenameValue(e.target.value)}
                                        onKeyDown={e => { if (e.key === 'Enter') finishRename(); if (e.key === 'Escape') setRenamingChatId(null); }}
                                        onBlur={finishRename}
                                        className="flex-1 bg-gray-800 border border-blue-500/50 rounded px-2 py-1 text-sm text-gray-200 focus:outline-none"
                                    />
                                </div>
                            ) : (
                                <div
                                    role="button"
                                    tabIndex={0}
                                    onClick={() => { setActiveChatId(chat.id); setMobileTab('chat'); }}
                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setActiveChatId(chat.id); setMobileTab('chat'); } }}
                                    className={clsx(
                                        "w-full text-left px-3 py-2.5 rounded-xl text-sm transition-all flex items-center gap-2.5 cursor-pointer",
                                        activeChatId === chat.id
                                            ? "bg-blue-500/20 text-blue-300 border border-blue-500/20"
                                            : "text-gray-400 hover:bg-white/5 border border-transparent"
                                    )}
                                >
                                    {(() => {
                                        const c = characters.find(ch => ch.id === chat.character_id);
                                        return (
                                            <div className="w-6 h-6 rounded-full bg-gray-700/60 flex items-center justify-center shrink-0 overflow-hidden border border-white/5">
                                                {c?.avatar_path
                                                    ? <img src={getAvatarUrl(c.id)} alt="" className="w-full h-full object-cover" />
                                                    : <MessageSquare size={10} className="text-gray-500" />
                                                }
                                            </div>
                                        );
                                    })()}
                                    <span className="truncate flex-1">{chat.name || 'Unnamed Chat'}</span>
                                    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                                        <button onClick={e => { e.stopPropagation(); startRename(chat); }} className="p-1 hover:text-white text-gray-500 rounded"><Edit3 size={11} /></button>
                                        <button onClick={e => { e.stopPropagation(); handleDeleteChat(chat); }} className="p-1 hover:text-red-400 text-gray-500 rounded"><Trash2 size={11} /></button>
                                    </div>
                                </div>
                            )}
                        </div>
                    ))}
                    {hasMoreChats && (
                        <button
                            onClick={() => setChatOffset(o => o + CHAT_PAGE_SIZE)}
                            className="w-full py-2 text-xs text-gray-500 hover:text-blue-300 hover:bg-white/5 rounded-lg transition-colors"
                        >
                            Load more chats
                        </button>
                    )}
                </div>
            </div>

            <div className={clsx(
                "flex-col min-w-0 bg-[#0B0E14] relative flex-1 lg:flex-auto",
                mobileTab === 'chat' ? "flex" : "hidden lg:flex"
            )}>
                <div className="h-12 lg:h-16 border-b border-white/5 flex items-center justify-between px-3 sm:px-4 shrink-0 bg-gray-900/40 backdrop-blur-md z-10 gap-2">
                    <div className="flex items-center gap-2 sm:gap-3 min-w-0 flex-1">
                        <button
                            type="button"
                            onClick={() => setChatsCollapsed(c => !c)}
                            className="hidden lg:flex p-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors shrink-0"
                            title={chatsCollapsed ? 'Show chats panel' : 'Hide chats panel'}
                        >
                            {chatsCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
                        </button>
                        <button 
                            type="button"
                            onClick={() => linkedCharacter?.avatar_path && handleAvatarClick(getAvatarUrl(linkedCharacter.id))}
                            className={clsx(
                                "w-9 h-9 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0 overflow-hidden",
                                linkedCharacter?.avatar_path && "cursor-pointer hover:border-blue-500/50 transition-colors"
                            )}
                        >
                            {linkedCharacter?.avatar_path
                                ? <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-full h-full object-cover" />
                                : <MessageSquare className="text-blue-400" size={16} />
                            }
                        </button>
                        <div className="min-w-0 flex-1">
                            <h2 className="font-semibold text-gray-100 flex items-center gap-2 text-sm sm:text-base">
                                <span className="truncate">{activeChat?.name || 'Roleplay Session'}</span>
                                <button
                                    onClick={triggerAutoTitle}
                                    disabled={isGeneratingTitle}
                                    className="text-[9px] bg-blue-500/10 text-blue-400 px-1.5 py-0.5 rounded hover:bg-blue-500/20 transition-colors flex items-center gap-1 disabled:opacity-50 shrink-0"
                                >
                                    {isGeneratingTitle ? <Loader2 size={9} className="animate-spin" /> : <Sparkles size={9} />}
                                    <span className="hidden sm:inline">Title</span>
                                </button>
                            </h2>
                            <p className="text-[10px] text-gray-500 truncate">
                                {linkedCharacter ? `${linkedCharacter.name}` : (activeChatId ? 'No character' : 'Select a chat')}
                                {activeChat?.persona_name && ` · as ${activeChat.persona_name}`}
                            </p>
                        </div>
                    </div>
                    
                    <div className="hidden md:flex items-center gap-2 mr-1 shrink-0">
                        {activeChat?.story_time && (
                            <div className="px-2.5 py-1 bg-gray-800/50 border border-white/5 rounded text-[11px] font-medium text-gray-300 flex items-center gap-1.5 shadow-sm" title="Story Time">
                                <Clock size={12} className="text-indigo-400/70" /> 
                                <span className="max-w-[120px] truncate">{activeChat.story_time}</span>
                            </div>
                        )}
                        {activeChat?.story_location && (
                            <div className="px-2.5 py-1 bg-gray-800/50 border border-white/5 rounded text-[11px] font-medium text-gray-300 flex items-center gap-1.5 shadow-sm" title="Story Location">
                                <MapPin size={12} className="text-rose-400/70" /> 
                                <span className="max-w-[160px] truncate">{activeChat.story_location}</span>
                            </div>
                        )}
                    </div>
                    <button
                        onClick={handleExportChat}
                        disabled={!activeChatId || !messages.length}
                        className="p-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors disabled:opacity-30 disabled:cursor-not-allowed hidden lg:block"
                        title="Export chat as Markdown"
                    >
                        <Download size={18} />
                    </button>
                    {contextCollapsed && (
                        <button
                            onClick={() => setContextCollapsed(false)}
                            className="hidden lg:flex p-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors shrink-0"
                            title="Show Context & Settings panel"
                        >
                            <PanelRightOpen size={18} />
                        </button>
                    )}
                </div>
                <div className="flex-1 overflow-y-auto p-3 sm:p-4 lg:p-6 custom-scrollbar" ref={listContainerRef}>
                    {!activeChatId && messages.length === 0 ? (
                        <div className="flex-1 flex flex-col items-center justify-center text-center opacity-50 gap-3">
                            <Sparkles className="w-10 h-10 text-blue-500 opacity-50" />
                            <div>
                                <h3 className="text-base font-medium text-gray-300">Chat Workspace</h3>
                                <p className="text-sm text-gray-500 max-w-xs mt-1">
                                    Select a chat or create a new one to begin your roleplay.
                                </p>
                            </div>
                        </div>
                    ) : (
                        <>
                            {hasMoreMessages && (
                                <div className="flex justify-center pb-3">
                                    <button
                                        onClick={loadOlderMessages}
                                        className="px-3 py-1.5 text-xs text-gray-400 hover:text-blue-300 hover:bg-blue-500/10 border border-white/5 rounded-lg transition-colors"
                                    >
                                        Load older messages
                                    </button>
                                </div>
                            )}
                            <div style={{ height: `${rowVirtualizer.getTotalSize()}px`, position: 'relative', width: '100%' }}>
                                {rowVirtualizer.getVirtualItems().map(virtualItem => (
                                    <div
                                        key={listItems[virtualItem.index]._key || virtualItem.index}
                                        data-index={virtualItem.index}
                                        ref={rowVirtualizer.measureElement}
                                        className="mb-4 flex flex-col"
                                        style={{
                                            position: 'absolute',
                                            top: 0,
                                            left: 0,
                                            width: '100%',
                                            transform: `translateY(${virtualItem.start}px)`,
                                        }}
                                    >
                                        {renderRow(listItems[virtualItem.index])}
                                    </div>
                                ))}
                            </div>
                            <div ref={messagesEndRef} />
                        </>
                    )}
                </div>

                <div className="px-3 sm:px-4 lg:px-6 py-3 sm:py-4 pb-4 border-t border-white/5 bg-gray-900/40 backdrop-blur-md shrink-0">
                    <div className="max-w-4xl mx-auto">
                        {pendingAttachment && (
                            <div className="mb-2 flex items-center gap-2 px-3 py-2 bg-blue-500/10 border border-blue-500/20 rounded-xl text-sm text-blue-300">
                                <ImageIcon size={13} className="shrink-0" />
                                <span className="truncate flex-1 text-xs">{pendingAttachment.name}</span>
                                <button onClick={() => setPendingAttachment(null)} className="p-1 hover:text-red-400 transition-colors shrink-0">
                                    <X size={13} />
                                </button>
                            </div>
                        )}
                        <div className="relative">
                            <CommandPalette
                                message={message}
                                activeCommand={activeCommand}
                                onSelect={(c) => {
                                    if (c.noArgs) {
                                        setMessage('');
                                        textareaRef.current?.blur();
                                        if (c.cmd === '/suggest') handleSuggestClick();
                                    } else {
                                        setActiveCommand(c);
                                        setMessage('');
                                        textareaRef.current?.focus();
                                    }
                                }}
                            />
                            <input ref={fileInputRef} type="file" accept="image/*" onChange={handleAttachmentChange} className="hidden" />
                            
                            <StreamingInput
                                textareaRef={textareaRef}
                                value={message}
                                onChange={handleTextChange}
                                onKeyDown={handleKeyDown}
                                placeholder={activeCommand ? activeCommand.argPlaceholder : (activeChatId ? 'Type a message...' : 'Select a chat to start...')}
                                disabled={sendMessageMutation.isPending || !activeChatId}
                                activeCommand={activeCommand}
                                onClearCommand={() => { setActiveCommand(null); setMessage(activeCommand.cmd + ' ' + message); }}
                            />

                            {/* Left Button */}
                            <button
                                onClick={() => fileInputRef.current?.click()}
                                disabled={isUploading}
                                className="absolute left-2 sm:left-3 bottom-2.5 sm:bottom-3 p-1.5 sm:p-2 text-gray-400 hover:text-blue-400 transition-colors rounded-xl hover:bg-blue-500/10 disabled:opacity-50"
                                title="Attach image"
                            >
                                {isUploading ? <Loader2 size={18} className="animate-spin" /> : <Paperclip size={18} />}
                            </button>

                            {/* Right Buttons Group */}
                            <div className="absolute right-2 sm:right-3 bottom-2.5 sm:bottom-3 flex items-center gap-1">
                                {/* Mobile overflow menu — keeps the 5 secondary tools
                                    reachable without letting 6 touch-sized buttons
                                    (~284px) cover the whole textarea on phones. */}
                                <button
                                    onClick={() => setShowMoreTools(v => !v)}
                                    className="sm:hidden p-1.5 text-gray-400 hover:text-white transition-colors rounded-xl hover:bg-white/10"
                                    title="More tools"
                                    aria-label="More tools"
                                >
                                    <MoreHorizontal size={18} />
                                </button>

                                {showMoreTools && (
                                    <div className="absolute bottom-full right-0 mb-2 w-48 bg-gray-900/95 backdrop-blur-xl border border-gray-700/60 rounded-2xl shadow-2xl overflow-hidden z-50 animate-in fade-in slide-in-from-bottom-2">
                                        <div className="px-3 py-2 text-xs font-semibold text-gray-400 bg-gray-800/40 uppercase tracking-wider border-b border-gray-700/50">Tools</div>
                                        <div className="flex flex-col p-1">
                                            <button
                                                onClick={() => { setShowMoreTools(false); handleGenerateScene(); }}
                                                disabled={isGeneratingScene || !activeChatId}
                                                className="flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left text-sm text-gray-200 disabled:opacity-50"
                                            >
                                                <ImageIcon size={16} className="text-green-400" />
                                                {isGeneratingScene ? 'Generating...' : 'Generate scene'}
                                            </button>
                                            <button
                                                onClick={() => { setShowMoreTools(false); handleIllustrate(); }}
                                                disabled={illustrateMutation.isPending || !activeChatId}
                                                className="flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left text-sm text-gray-200 disabled:opacity-50"
                                            >
                                                <Palette size={16} className="text-pink-400" />
                                                {illustrateMutation.isPending ? 'Illustrating...' : 'Illustrate moment'}
                                            </button>
                                            <button
                                                onClick={() => { setShowMoreTools(false); setAgenticMode(!agenticMode); }}
                                                className={clsx("flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left text-sm", agenticMode ? "text-purple-400" : "text-gray-200")}
                                            >
                                                <Wand2 size={16} className="text-purple-400" />
                                                Agentic {agenticMode ? 'ON' : 'OFF'}
                                            </button>
                                            <button
                                                onClick={() => { setShowMoreTools(false); setNarrateMode(!narrateMode); }}
                                                className={clsx("flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left text-sm", narrateMode ? "text-purple-400" : "text-gray-200")}
                                            >
                                                <BookOpen size={16} className="text-purple-400" />
                                                Narrate {narrateMode ? 'ON' : 'OFF'}
                                            </button>
                                            <button
                                                onClick={() => { setShowMoreTools(false); handleImpersonate(); }}
                                                disabled={!activeChatId || impersonateMutation.isPending}
                                                className="flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left text-sm text-gray-200 disabled:opacity-50"
                                            >
                                                <Ghost size={16} className="text-purple-400" />
                                                {impersonateMutation.isPending ? 'Impersonating...' : 'Impersonate'}
                                            </button>
                                            <button
                                                onClick={() => { setShowMoreTools(false); handleSuggestClick(); }}
                                                disabled={!activeChatId || suggestReplyMutation.isPending || suggestJobId}
                                                className="flex items-center gap-2.5 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left text-sm text-gray-200 disabled:opacity-50"
                                            >
                                                <Sparkles size={16} className="text-blue-400" />
                                                {(suggestReplyMutation.isPending || suggestJobId) ? 'Suggesting...' : 'Suggest reply'}
                                            </button>
                                        </div>
                                    </div>
                                )}

                                {/* Secondary tools — inline on sm+ screens only */}
                                <div className="hidden sm:flex items-center gap-1">
                                {/* Generate scene */}
                                <button
                                    onClick={handleGenerateScene}
                                    disabled={isGeneratingScene || !activeChatId}
                                    className="p-1.5 sm:p-2 text-gray-400 hover:text-green-400 transition-colors rounded-xl hover:bg-green-500/10 disabled:opacity-50"
                                    title="Generate Scene"
                                >
                                    {isGeneratingScene ? <Loader2 size={18} className="animate-spin" /> : <ImageIcon size={18} />}
                                </button>
                                {/* Illustrate moment — direct image job from draft or last reply */}
                                <button
                                    onClick={handleIllustrate}
                                    disabled={illustrateMutation.isPending || !activeChatId}
                                    className={clsx(
                                        "p-1.5 sm:p-2 transition-colors rounded-xl",
                                        illustrateMutation.isPending
                                            ? "text-pink-400 bg-pink-500/10 cursor-not-allowed"
                                            : (activeChatId ? "text-gray-400 hover:text-pink-400 hover:bg-pink-500/10" : "text-gray-600 cursor-not-allowed")
                                    )}
                                    title="Illustrate moment — generates an image from your draft or the latest reply"
                                >
                                    {illustrateMutation.isPending ? <Loader2 size={18} className="animate-spin" /> : <Palette size={18} />}
                                </button>
                                {/* Agentic mode */}
                                <button
                                    onClick={() => setAgenticMode(!agenticMode)}
                                    className={clsx(
                                        "p-1.5 sm:p-2 transition-colors rounded-xl",
                                        agenticMode
                                            ? "text-purple-400 hover:text-purple-300 hover:bg-purple-500/10"
                                            : "text-gray-500 hover:text-gray-400 hover:bg-white/5"
                                    )}
                                    title={agenticMode ? "Agentic ON" : "Agentic OFF"}
                                >
                                    <Wand2 size={18} />
                                </button>
                                {/* Narrate mode */}
                                <button
                                    onClick={() => setNarrateMode(!narrateMode)}
                                    className={clsx(
                                        "p-1.5 sm:p-2 transition-colors rounded-xl",
                                        narrateMode
                                            ? "text-purple-400 hover:text-purple-300 hover:bg-purple-500/10"
                                            : "text-gray-500 hover:text-gray-400 hover:bg-white/5"
                                    )}
                                    title={narrateMode ? "Narrate ON — next message triggers the narrator" : "Narrate OFF"}
                                >
                                    <BookOpen size={18} />
                                </button>
                                {/* Impersonate */}
                                <button
                                    onClick={() => handleImpersonate()}
                                    disabled={!activeChatId || impersonateMutation.isPending}
                                    className={clsx(
                                        "p-1.5 sm:p-2 transition-all rounded-xl",
                                        impersonateMutation.isPending
                                            ? "text-purple-400 bg-purple-500/10 cursor-not-allowed"
                                            : (activeChatId ? "text-gray-400 hover:text-purple-400 hover:bg-purple-500/10" : "text-gray-600 cursor-not-allowed")
                                    )}
                                    title="Impersonate — AI writes your next message then triggers a reply"
                                >
                                    {impersonateMutation.isPending
                                        ? <Loader2 size={16} className="animate-spin" />
                                        : <Ghost size={16} />}
                                </button>
                                {/* Suggest */}
                                <button
                                    onClick={handleSuggestClick}
                                    disabled={!activeChatId || suggestReplyMutation.isPending || suggestJobId}
                                    className={clsx(
                                        "p-1.5 sm:p-2 transition-all rounded-xl",
                                        (suggestReplyMutation.isPending || suggestJobId)
                                            ? "text-blue-400 bg-blue-500/10 cursor-not-allowed"
                                            : (activeChatId ? "text-blue-400 hover:text-white hover:bg-blue-600/50" : "text-gray-600 cursor-not-allowed")
                                    )}
                                    title="Auto-suggest reply"
                                >
                                    {(suggestReplyMutation.isPending || suggestJobId) 
                                        ? <Loader2 size={16} className="animate-spin" />
                                        : <Sparkles size={16} />}
                                </button>
                                </div>
                                {/* Send */}
                                <button
                                    onClick={handleSendMessage}
                                    disabled={!canSend}
                                    className={clsx(
                                        "p-1.5 sm:p-2 transition-all rounded-xl",
                                        canSend
                                            ? "bg-blue-600 text-white shadow-[0_0_12px_rgba(37,99,235,0.4)] hover:bg-blue-500 hover:scale-105"
                                            : "bg-gray-800 text-gray-500 cursor-not-allowed"
                                    )}
                                >
                                    {sendMessageMutation.isPending
                                        ? <Loader2 size={16} className="animate-spin" />
                                        : <Send size={16} className={canSend ? "translate-x-0.5 -translate-y-0.5" : ""} />
                                    }
                                </button>
                            </div>
                        </div>
                        <div className="mt-1.5 hidden sm:flex items-center justify-between px-1 text-[10px] text-gray-600">
                            <span><kbd className="font-mono bg-gray-800 px-1 py-0.5 rounded border border-gray-700 text-gray-500">Enter</kbd> to send · <kbd className="font-mono bg-gray-800 px-1 py-0.5 rounded border border-gray-700 text-gray-500">Shift+Enter</kbd> for newline</span>
                            <span className="flex items-center gap-2">
                                {narrateMode && (
                                    <span className="text-purple-400">📖 Narrate</span>
                                )}
                                <span className={clsx("transition-colors", agenticMode ? "text-purple-400" : "text-gray-600")}>
                                    {agenticMode ? '⚡ Agentic' : 'Standard'}
                                </span>
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            {/* === CONTEXT PANEL (Right) === */}
            <div className={clsx(
                "flex-col shrink-0 border-l border-white/5 bg-gray-900 lg:bg-gray-900/70 flex-1 lg:flex-none overflow-hidden min-w-0",
                "w-full",
                contextCollapsed ? "lg:w-0 lg:border-l-0" : "lg:w-72",
                mobileTab === 'context' ? "flex" : "hidden lg:flex"
            )}>
                <div className="h-12 lg:h-16 border-b border-white/5 flex items-center justify-between px-4 shrink-0 bg-gray-900/60 backdrop-blur-md">
                    <h3 className="font-semibold text-gray-200 flex items-center gap-2 text-sm">
                        <Settings size={14} className="text-gray-400" />
                        Context &amp; Settings
                    </h3>
                    <button
                        onClick={() => setMobileTab('chat')}
                        className="lg:hidden p-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors"
                    >
                        <X size={16} />
                    </button>
                    <button
                        onClick={() => setContextCollapsed(c => !c)}
                        className="hidden lg:flex p-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors"
                        title="Hide context panel"
                    >
                        <PanelRightClose size={18} />
                    </button>
                </div>

                <ChatContextPanel
                    activeChat={activeChat}
                    linkedCharacter={linkedCharacter}
                    chatJobs={chatJobs}
                    chatCollection={chatCollection}
                    activeStreamEntries={activeStreamEntries}
                    sceneJobId={sceneJobId}
                    characters={characters}
                    lorebooks={lorebooks}
                    selectedLorebooks={selectedLorebooks}
                    systemPromptData={systemPromptData}
                    availableModels={availableModels}
                    defaultLlmConfig={defaultLlmConfig}
                    onChatUpdate={handleChatUpdate}
                    onCharacterPatch={(updates) => {
                        if (!linkedCharacter) return;
                        patchCharacterMutation.mutate({ id: linkedCharacter.id, ...updates });
                    }}
                    onShowCharacterDetails={() => setShowCharacterDetails(true)}
                    onShowScenes={() => setShowScenesModal(true)}
                />
            </div>
            </div>{/* === END THREE-COLUMN ROW === */}

            {/* === MODALS === */}
            <AnimatePresence>
                {showNewChatModal && (
                    <NewChatModal
                        characters={characters}
                        lorebooks={lorebooks}
                        onCreate={confirmCreateChat}
                        onClose={() => setShowNewChatModal(false)}
                    />
                )}
                {showCharacterDetails && (
                    <CharacterDetailsModal
                        character={linkedCharacter}
                        onClose={() => setShowCharacterDetails(false)}
                    />
                )}
                {greetingModal && (
                    <GreetingPickerModal
                        character={greetingModal.character}
                        onSelect={greetingModal.onCreate}
                        onClose={() => { setGreetingModal(null); hasCreatedChatRef.current = false; }}
                    />
                )}
            </AnimatePresence>

            {showScenesModal && (
                <div className="fixed inset-0 z-[60] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
                    <motion.div
                        initial={{ scale: 0.95, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0.95, opacity: 0 }}
                        className="w-full max-w-5xl bg-gray-900 border border-white/10 rounded-3xl shadow-2xl flex flex-col h-[85vh]"
                    >
                        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 shrink-0">
                            <h3 className="font-bold text-gray-100 flex items-center gap-2">
                                <ImageIcon size={16} className="text-purple-400" />
                                {linkedCharacter?.name || 'Character'} Scenes
                            </h3>
                            <button onClick={() => setShowScenesModal(false)} className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                                <X size={18} />
                            </button>
                        </div>
                        <div className="flex gap-2 px-6 pt-4 shrink-0">
                            <button
                                onClick={() => setSceneTab('chat')}
                                className={clsx('px-4 py-1.5 rounded-xl text-xs font-medium transition-colors', sceneTab === 'chat' ? 'bg-purple-500/20 text-purple-300' : 'bg-gray-800/60 text-gray-400 hover:text-gray-200')}
                            >
                                This chat ({chatImages.length})
                            </button>
                            <button
                                onClick={() => setSceneTab('collection')}
                                className={clsx('px-4 py-1.5 rounded-xl text-xs font-medium transition-colors', sceneTab === 'collection' ? 'bg-purple-500/20 text-purple-300' : 'bg-gray-800/60 text-gray-400 hover:text-gray-200')}
                            >
                                Character collection ({chatCollection?.image_count || 0})
                            </button>
                        </div>
                        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
                            {sceneTab === 'chat' ? (
                                <SceneGallery
                                    title={`${linkedCharacter?.name || 'Character'} chat scenes`}
                                    images={chatImages.map(img => img.path)}
                                    lightboxAction={(path) => (
                                        <select
                                            value=""
                                            onChange={(e) => {
                                                if (e.target.value) {
                                                    handleSaveImageToCollection(e.target.value, path);
                                                    e.target.value = '';
                                                }
                                            }}
                                            className="bg-gray-800 border border-white/10 rounded-lg text-xs text-gray-200 px-2 py-1.5 cursor-pointer hover:border-blue-500/40 transition-colors"
                                            title="Save to collection"
                                        >
                                            <option value="">Save to…</option>
                                            {collectionsList.map(c => (
                                                <option key={c.id} value={c.id}>{c.name}</option>
                                            ))}
                                        </select>
                                    )}
                                />
                            ) : (
                                <SceneGallery
                                    title={`${linkedCharacter?.name || 'Character'} scenes`}
                                    images={chatCollection?.images || []}
                                />
                            )}
                        </div>
                    </motion.div>
                </div>
            )}
            {avatarModalSrc && (
                <div className="fixed inset-0 z-[100] bg-black/85 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setAvatarModalSrc(null)}>
                    <div className="flex items-center justify-between w-full absolute top-0 left-0 right-0 px-4 py-3">
                        <span className="text-xs text-gray-400">{linkedCharacter?.name || 'Avatar'}</span>
                        <button className="p-2 text-gray-300 hover:text-white rounded-xl hover:bg-white/10 transition-colors" onClick={() => setAvatarModalSrc(null)}>
                            <X size={18} />
                        </button>
                    </div>
                    <img
                        src={avatarModalSrc}
                        alt="Avatar"
                        className="max-h-[85vh] max-w-full rounded-xl shadow-2xl object-contain"
                        onClick={(e) => e.stopPropagation()}
                    />
                </div>
            )}
            {/* Shared mobile bottom tab bar (replaces the inline tab strip — issue #1/#1.2) */}
            <BottomTabBar
                inline
                tabs={[
                    { id: 'chats', label: 'Chats', icon: MessageSquare, color: 'text-blue-400' },
                    { id: 'chat', label: 'Roleplay', icon: Activity, color: 'text-purple-400' },
                    { id: 'context', label: 'Context', icon: Settings, color: 'text-amber-400' },
                ]}
                value={mobileTab}
                onChange={setMobileTab}
                label="Chat workspace navigation"
            />
        </motion.div>
    );
}
