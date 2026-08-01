import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, Send, Image as ImageIcon, Settings, PanelRightClose, PanelRightOpen, Paperclip, MoreVertical, Sparkles, Plus, Loader2, Trash2, Edit3, BookOpen, Check, Wand2 } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { useLocation } from 'react-router-dom';
import api from '../api/client';
import { useMessages, useChats, useSendMessage, useChat, useCreateChat, useDeleteChat, useLorebooks, useCharacters, useRenameChat, getAvatarUrl } from '../hooks/useWorldVault';
import worldVaultApi from '../api/worldVault';
import { useWorldVaultStore } from '../store/worldVaultStore';
import { useWebSocket, EventTypes } from '../api/websocket';
import { useQueryClient } from '@tanstack/react-query';
import ConfirmationModal from '../components/ConfirmationModal';

export default function ChatWorkspace() {
    const [isRightPanelOpen, setIsRightPanelOpen] = useState(true);
    const [message, setMessage] = useState('');
    const [renamingChatId, setRenamingChatId] = useState(null);
    const [renameValue, setRenameValue] = useState('');
    const [deleteTarget, setDeleteTarget] = useState(null);
    const [isGeneratingScene, setIsGeneratingScene] = useState(false);
    const [pendingAttachment, setPendingAttachment] = useState(null);
    const [isUploading, setIsUploading] = useState(false);
    const [agenticMode, setAgenticMode] = useState(true);
    const [isSidebarOpen, setIsSidebarOpen] = useState(false);
    const [isGeneratingTitle, setIsGeneratingTitle] = useState(false);
    const fileInputRef = useRef(null);
    const messagesEndRef = useRef(null);
    const location = useLocation();

    const queryClient = useQueryClient();
    const activeChatId = useWorldVaultStore(state => state.activeChatId);
    const setActiveChatId = useWorldVaultStore(state => state.setActiveChat);
    const updateStreamingJob = useWorldVaultStore(state => state.updateStreamingJob);
    const clearStreamingJob = useWorldVaultStore(state => state.clearStreamingJob);
    const streamingJobs = useWorldVaultStore(state => state.streamingJobs);
    const selectedLorebooks = useWorldVaultStore(state => state.contextBuilder.selectedLorebooks);
    const toggleLorebook = useWorldVaultStore(state => state.toggleLorebook);

    const { data: chats, isLoading: isChatsLoading } = useChats();
    const { data: activeChat } = useChat(activeChatId);
    const { data: messages = [] } = useMessages(activeChatId);
    const { data: lorebooks = [] } = useLorebooks();
    const { data: characters = [] } = useCharacters();

    const sendMessageMutation = useSendMessage();
    const createChatMutation = useCreateChat();
    const deleteChatMutation = useDeleteChat();
    const renameChatMutation = useRenameChat();

    const { subscribe } = useWebSocket();

    // Handle character_id from navigation state (e.g. from Characters page "Chat" button)
    useEffect(() => {
        const characterId = location.state?.characterId;
        if (characterId && !activeChatId) {
            createChatMutation.mutate(
                { name: 'New Chat', character_id: characterId },
                {
                    onSuccess: (chat) => {
                        setActiveChatId(chat.id);
                        window.history.replaceState({}, document.title);
                    }
                }
            );
        }
    }, [location.state?.characterId]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (chats?.length > 0 && !activeChatId) {
            setActiveChatId(chats[0].id);
        }
    }, [chats, activeChatId, setActiveChatId]);

    useEffect(() => {
        const unsubProgress = subscribe(EventTypes.JOB_PROGRESS, (event) => {
            const job = event.data?.job || event;
            const streamText = job.metadata_?.text || job.output?.text || job.progress_text;
            if (streamText && job.metadata_?.chat_id === activeChatId) {
                updateStreamingJob(job.id, { text: streamText, status: job.status, chatId: activeChatId });
            }
        });
        
        const unsubCompleted = subscribe(EventTypes.JOB_COMPLETED, (event) => {
            const job = event.data?.job || event;
            if (job.metadata_?.chat_id === activeChatId) {
                const eventType = job.type || job.metadata_?.type;
                if (eventType === 'chat_image' || eventType === 'story_image') {
                    toast.success('Image generated!', { icon: '🖼️' });
                } else if (eventType === 'tool_execution') {
                    toast.success('Tool executed: ' + (job.tool_name || 'unknown'), { icon: '🔧' });
                }
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', activeChatId] });
                if (job.id) clearStreamingJob(job.id);
            }
        });

        const unsubError = subscribe(EventTypes.JOB_FAILED, (event) => {
            const job = event.data?.job || event;
            if (job.metadata_?.chat_id === activeChatId) {
                toast.error('AI response failed. Please try again.');
                if (job.id) clearStreamingJob(job.id);
            }
        });

        return () => {
            unsubProgress();
            unsubCompleted();
            unsubError();
        };
    }, [subscribe, activeChatId, updateStreamingJob, clearStreamingJob, queryClient]);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, streamingJobs]);

    const handleSendMessage = async () => {
        if (!message.trim() && !pendingAttachment) return;
        
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

        const msgContent = message.trim();
        setMessage('');
        const attachmentFilename = pendingAttachment?.filename || null;
        setPendingAttachment(null);

        try {
            const res = await sendMessageMutation.mutateAsync({
                chatId: chatIdToUse,
                message: { role: 'user', content: msgContent, lorebook_ids: selectedLorebooks, image_path: attachmentFilename, agentic: agenticMode }
            });
            if (res.job_id) {
                updateStreamingJob(res.job_id, { text: '', status: 'running', chatId: chatIdToUse });
            }
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', chatIdToUse] });
        } catch (error) {
            toast.error('Failed to send message');
            console.error('Failed to send message:', error);
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSendMessage();
        }
    };

    const canSend = (message.trim() || pendingAttachment) && !sendMessageMutation.isPending;

    const handleGenerateScene = async () => {
        if (!activeChatId) return;
        setIsGeneratingScene(true);
        toast.success('Generating scene... This may take a moment.', { icon: '📸' });
        
        try {
            const res = await fetch(`/api/world_vault/chats/${activeChatId}/scene`, {
                method: 'POST'
            });
            if (!res.ok) throw new Error('Failed to generate scene');
            const data = await res.json();
            
            if (data.job_id) {
                updateStreamingJob(data.job_id, { text: 'Generating scene image...', status: 'running', chatId: activeChatId });
            }
        } catch (error) {
            console.error('Generate scene error:', error);
            toast.error('Failed to generate scene');
        } finally {
            setIsGeneratingScene(false);
        }
    };


    const triggerAutoTitle = async () => {
        if (!activeChatId) return;
        setIsGeneratingTitle(true);
        toast('Generating title...', { icon: '🤖' });
        
        try {
            const chatHistory = messages.slice(-5).map(m => `${m.role}: ${m.content}`).join('\n');
            const resJob = await api.post('/api/jobs', {
                task_type: "llm",
                workflow: {
                    messages: [
                        { role: "system", content: "You are a helpful assistant. Generate a short, catchy title (max 5 words) for the following chat history. Output ONLY the title." },
                        { role: "user", content: chatHistory || "A new conversation." }
                    ]
                }
            });
            
            const pollJob = async (jobId) => {
                for (let i = 0; i < 30; i++) {
                    const jobStatus = await api.get(`/api/jobs/${jobId}`);
                    if (jobStatus.status === 'completed' && jobStatus.outputs?.length > 0) {
                        const newTitle = jobStatus.outputs[0].content.replace(/["']/g, '');
                        await renameChatMutation.mutateAsync({ chatId: activeChatId, name: newTitle });
                        toast.success('Title generated!');
                        setIsGeneratingTitle(false);
                        return;
                    }
                    if (jobStatus.status === 'failed') break;
                    await new Promise(r => setTimeout(r, 1000));
                }
                toast.error('Title generation failed');
                setIsGeneratingTitle(false);
            };
            if (resJob.id) {
                pollJob(resJob.id);
            } else {
                setIsGeneratingTitle(false);
            }
        } catch {
            toast.error('Failed to generate title');
            setIsGeneratingTitle(false);
        }
    };

    const handleCreateChat = () => {
        createChatMutation.mutate({ name: 'New Chat' }, {
            onSuccess: (chat) => {
                setActiveChatId(chat.id);
                toast.success('New chat created');
            },
            onError: () => toast.error('Failed to create chat')
        });
    };

    const handleAttachmentClick = () => {
        fileInputRef.current?.click();
    };

    const handleAttachmentChange = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        e.target.value = '';

        if (file.size > 20 * 1024 * 1024) {
            toast.error('File too large (max 20MB)');
            return;
        }

        setIsUploading(true);
        try {
            const formData = new FormData();
            formData.append('file', file);
            const res = await worldVaultApi.upload.chatAttachment(formData);
            setPendingAttachment({ filename: res.filename, name: file.name });
            toast.success('Image attached');
        } catch {
            toast.error('Failed to upload image');
        } finally {
            setIsUploading(false);
        }
    };

    const removeAttachment = () => {
        setPendingAttachment(null);
    };

    const handleDeleteChat = async () => {
        if (!deleteTarget) return;
        try {
            await deleteChatMutation.mutateAsync(deleteTarget.id);
            if (activeChatId === deleteTarget.id) {
                const remaining = chats?.filter(c => c.id !== deleteTarget.id);
                setActiveChatId(remaining?.[0]?.id || null);
            }
            toast.success('Chat deleted');
        } catch {
            toast.error('Failed to delete chat');
        }
        setDeleteTarget(null);
    };

    const startRename = (chat) => {
        setRenamingChatId(chat.id);
        setRenameValue(chat.name || '');
    };

    const finishRename = async () => {
        if (renamingChatId && renameValue.trim()) {
            try {
                await renameChatMutation.mutateAsync({ chatId: renamingChatId, name: renameValue.trim() });
                toast.success('Chat renamed');
            } catch {
                toast.error('Failed to rename chat');
            }
        }
        setRenamingChatId(null);
    };

    const linkedCharacter = characters.find(c => c.id === activeChat?.character_id);

    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex h-[calc(100vh-8rem)] lg:h-[calc(100vh-4rem)] -mx-2 sm:-mx-4 lg:-mx-8 -my-3 sm:-my-4 lg:-my-8"
        >
            {/* Chats Sidebar Overlay for Mobile */}
            <AnimatePresence>
                {isSidebarOpen && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-40 bg-black/50 md:hidden"
                        onClick={() => setIsSidebarOpen(false)}
                    />
                )}
            </AnimatePresence>

            {/* Sidebar for Chats */}
            <div className={clsx(
                "absolute md:static inset-y-0 left-0 z-50 transform md:transform-none transition-transform duration-300 ease-in-out h-full flex flex-col shrink-0 w-64 border-r border-white/5 bg-gray-900/60",
                isSidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
            )}>
                <div className="h-16 flex items-center justify-between px-4 border-b border-white/5 shrink-0">
                    <h3 className="font-semibold text-gray-200">Chats</h3>
                    <button onClick={handleCreateChat} className="p-1.5 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors">
                        <Plus size={18} />
                    </button>
                </div>
                <div className="flex-1 overflow-y-auto p-2 space-y-1">
                    {isChatsLoading ? (
                        <div className="flex justify-center p-4"><Loader2 className="animate-spin text-gray-500" /></div>
                    ) : (
                        chats?.map(chat => (
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
                                    <button
                                        onClick={() => { setActiveChatId(chat.id); setIsSidebarOpen(false); }}
                                        className={clsx(
                                            "w-full text-left px-3 py-2 rounded-lg text-sm transition-colors flex items-center justify-between",
                                            activeChatId === chat.id ? "bg-blue-500/20 text-blue-300" : "text-gray-400 hover:bg-white/5"
                                        )}
                                    >
                                        <span className="truncate">{chat.name || 'Unnamed Chat'}</span>
                                        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0 ml-2">
                                            <button onClick={(e) => { e.stopPropagation(); startRename(chat); }} className="p-1 hover:text-white text-gray-500 rounded"><Edit3 size={12} /></button>
                                            <button onClick={(e) => { e.stopPropagation(); setDeleteTarget(chat); }} className="p-1 hover:text-red-400 text-gray-500 rounded"><Trash2 size={12} /></button>
                                        </div>
                                    </button>
                                )}
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Left Panel: Chat Interface */}
            <div className="flex-1 flex flex-col min-w-0 bg-[#0B0E14] relative">
                {/* Chat Header */}
                <div className="h-16 border-b border-white/5 flex items-center justify-between px-2 sm:px-4 lg:px-6 shrink-0 bg-gray-900/40 backdrop-blur-md z-10 gap-2">
                    <div className="flex items-center gap-2 sm:gap-3 min-w-0 flex-1">
                        <div className="md:hidden">
                            <button onClick={() => setIsSidebarOpen(true)} className="p-1.5 sm:p-2 text-gray-400 hover:text-white transition-colors">
                                <MessageSquare size={20} />
                            </button>
                        </div>
                        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center overflow-hidden shrink-0 hidden sm:flex">
                            {linkedCharacter?.has_avatar ? (
                                <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-full h-full object-cover" />
                            ) : (
                                <MessageSquare className="text-blue-400" size={20} />
                            )}
                        </div>
                        <div className="min-w-0 flex-1">
                            <h2 className="font-semibold text-gray-100 flex items-center gap-2">
                                <span className="truncate">{activeChat?.name || 'Roleplay Session'}</span>
                                <button 
                                    onClick={triggerAutoTitle} 
                                    disabled={isGeneratingTitle}
                                    className="ml-1 sm:ml-2 text-[10px] bg-blue-500/10 text-blue-400 px-1.5 py-0.5 rounded hover:bg-blue-500/20 transition-colors flex items-center gap-1 disabled:opacity-50 shrink-0"
                                    title="Auto-generate chat title using AI"
                                >
                                    {isGeneratingTitle ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
                                    <span className="hidden sm:inline">Auto Title</span>
                                </button>
                            </h2>
                            <p className="text-[10px] sm:text-xs text-gray-500 truncate min-w-0">
                                {linkedCharacter ? `Playing as ${linkedCharacter.name}` : (activeChatId ? `Chat ID: ${activeChatId.slice(0, 8)}...` : 'No chat selected')}
                            </p>
                        </div>
                    </div>
                    
                    <div className="flex items-center gap-1 sm:gap-2 shrink-0">
                        <button 
                            onClick={() => setIsRightPanelOpen(!isRightPanelOpen)}
                            className="p-2 text-gray-400 hover:text-gray-200 hover:bg-white/5 rounded-lg transition-colors hidden lg:flex"
                            title="Toggle Context Panel"
                        >
                            {isRightPanelOpen ? <PanelRightClose size={20} /> : <PanelRightOpen size={20} />}
                        </button>
                    </div>
                </div>

                {/* Chat Messages Area */}
                <div className="flex-1 overflow-y-auto p-4 lg:p-6 space-y-6 custom-scrollbar flex flex-col">
                    {!activeChatId && messages.length === 0 ? (
                        <div className="flex-1 flex flex-col items-center justify-center text-center opacity-50">
                            <Sparkles className="w-12 h-12 text-blue-500 mb-4 opacity-50" />
                            <h3 className="text-lg font-medium text-gray-300">Welcome to the Chat Workspace</h3>
                            <p className="text-sm text-gray-500 max-w-md mt-2">
                                Select or create a chat to begin. The AI can automatically generate images, audio, and tools during the conversation.
                            </p>
                        </div>
                    ) : (
                        <>
                            {messages.map((msg, idx) => (
                                <div key={msg.id || idx} className={clsx(
                                    "flex flex-col max-w-[85%]",
                                    msg.role === 'user' ? "self-end items-end" : "self-start items-start"
                                )}>
                                    <div className="text-xs text-gray-500 mb-1 ml-1">
                                        {msg.role === 'user' ? 'You' : msg.role === 'system' ? 'System' : 'AI'}
                                    </div>
                                    <div className={clsx(
                                        "p-4 rounded-2xl whitespace-pre-wrap text-sm",
                                        msg.role === 'user' 
                                            ? "bg-blue-600/20 text-blue-100 border border-blue-500/20 rounded-tr-sm" 
                                            : msg.role === 'system'
                                            ? "bg-yellow-500/10 text-yellow-200 border border-yellow-500/20 rounded-tl-sm italic"
                                            : "bg-gray-800/40 text-gray-200 border border-gray-700/50 rounded-tl-sm"
                                    )}>
                                        {msg.content}
                                        {msg.image_path && (
                                            <div className="mt-3">
                                                <img src={`/api/files/${msg.image_path}`} alt="Scene" className="rounded-xl max-w-full h-auto border border-white/10 shadow-lg" />
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ))}
                            
                            {Object.entries(streamingJobs).map(([jobId, jobData]) => (
                                jobData.status === 'running' && jobData.chatId === activeChatId && (
                                    <div key={jobId} className="flex flex-col max-w-[85%] self-start items-start">
                                        <div className="text-xs text-blue-400 mb-1 ml-1 flex items-center gap-2">
                                            {jobData.text?.includes('[Tool:') ? '🔧 Tool' : 'AI'} <Loader2 size={12} className="animate-spin" />
                                        </div>
                                        <div className="p-4 rounded-2xl whitespace-pre-wrap text-sm bg-gray-800/40 text-gray-200 border border-gray-700/50 rounded-tl-sm">
                                            {jobData.text ? jobData.text + "..." : (
                                                <span className="flex items-center gap-2 text-purple-400">
                                                    <Wand2 size={14} className="animate-pulse" />
                                                    Executing tools...
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                )
                            ))}
                            <div ref={messagesEndRef} />
                        </>
                    )}
                </div>

                {/* Chat Input Area */}
                <div className="p-4 lg:p-6 border-t border-white/5 bg-gray-900/40 backdrop-blur-md shrink-0">
                    <div className="max-w-4xl mx-auto">
                        {pendingAttachment && (
                            <div className="mb-2 flex items-center gap-2 px-3 py-2 bg-blue-500/10 border border-blue-500/20 rounded-lg text-sm text-blue-300">
                                <ImageIcon size={14} className="shrink-0" />
                                <span className="truncate flex-1">{pendingAttachment.name}</span>
                                <button onClick={removeAttachment} className="p-1 hover:text-red-400 transition-colors shrink-0">
                                    <Trash2 size={14} />
                                </button>
                            </div>
                        )}
                        <div className="relative group">
                            <input
                                ref={fileInputRef}
                                type="file"
                                accept="image/*"
                                onChange={handleAttachmentChange}
                                className="hidden"
                            />
                            <textarea
                                value={message}
                                onChange={(e) => setMessage(e.target.value)}
                                onKeyDown={handleKeyDown}
                                placeholder="Type a message..."
                                className="w-full bg-gray-900/80 border border-gray-700/50 rounded-2xl pl-12 pr-32 sm:pr-40 py-4 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50 transition-all resize-none shadow-inner text-sm sm:text-base"
                                rows={1}
                                style={{ minHeight: '60px', maxHeight: '200px' }}
                                disabled={sendMessageMutation.isPending}
                            />
                            <button
                                onClick={handleAttachmentClick}
                                disabled={isUploading}
                                className="absolute left-3 bottom-3 p-2 text-gray-400 hover:text-blue-400 transition-colors rounded-xl hover:bg-blue-500/10 disabled:opacity-50"
                                title="Attach image"
                            >
                                {isUploading ? <Loader2 size={20} className="animate-spin" /> : <Paperclip size={20} />}
                            </button>
                            <button 
                                onClick={handleGenerateScene}
                                disabled={isGeneratingScene || !activeChatId}
                                className="absolute right-12 bottom-3 p-2 text-gray-400 hover:text-green-400 transition-colors rounded-xl hover:bg-green-500/10 disabled:opacity-50"
                                title="Generate Scene Image"
                                type="button"
                            >
                                {isGeneratingScene ? <Loader2 size={20} className="animate-spin" /> : <ImageIcon size={20} />}
                            </button>
                            <button 
                                onClick={() => setAgenticMode(!agenticMode)}
                                className={clsx(
                                    "absolute right-24 bottom-3 p-2 transition-colors rounded-xl",
                                    agenticMode
                                        ? "text-purple-400 hover:text-purple-300 hover:bg-purple-500/10"
                                        : "text-gray-500 hover:text-gray-400 hover:bg-white/5"
                                )}
                                title={agenticMode ? "Agentic mode ON (AI can generate images)" : "Agentic mode OFF"}
                                type="button"
                            >
                                <Wand2 size={20} />
                            </button>
                            <button 
                                onClick={handleSendMessage}
                                disabled={!canSend}
                                className={clsx(
                                    "absolute right-2 bottom-3 p-2 transition-all rounded-xl",
                                    canSend
                                        ? "bg-blue-600 text-white shadow-[0_0_15px_rgba(37,99,235,0.4)] hover:bg-blue-500 hover:scale-105" 
                                        : "bg-gray-800 text-gray-500 cursor-not-allowed"
                                )}
                            >
                                {sendMessageMutation.isPending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} className={canSend ? "translate-x-0.5 -translate-y-0.5" : ""} />}
                            </button>
                        </div>
                    </div>
                    <div className="max-w-4xl mx-auto mt-2 hidden sm:flex items-center justify-between px-2 text-[10px] text-gray-500">
                        <span>Press <kbd className="font-mono bg-gray-800 px-1 py-0.5 rounded border border-gray-700">Enter</kbd> to send</span>
                    </div>
                </div>
            </div>

            {/* Right Panel: Context */}
            <AnimatePresence initial={false}>
                {isRightPanelOpen && (
                    <motion.div
                        initial={{ width: 0, opacity: 0 }}
                        animate={{ width: 360, opacity: 1 }}
                        exit={{ width: 0, opacity: 0 }}
                        transition={{ duration: 0.3, ease: "easeInOut" }}
                        className={clsx(
                            "flex flex-col border-l border-white/5 bg-gray-900/95 overflow-hidden shrink-0",
                            "absolute md:static inset-y-0 right-0 z-40 h-full max-w-full w-[360px] md:w-auto md:bg-gray-900/30"
                        )}
                    >
                        {/* Mobile close button for right panel */}
                        <div className="md:hidden absolute top-3 right-4 z-50">
                            <button onClick={() => setIsRightPanelOpen(false)} className="p-2 bg-gray-800 rounded-full text-white">
                                <PanelRightClose size={16} />
                            </button>
                        </div>
                        <div className="h-16 border-b border-white/5 flex items-center px-4 shrink-0 bg-gray-900/60 backdrop-blur-md">
                            <h3 className="font-semibold text-gray-200 flex items-center gap-2">
                                <Settings size={16} className="text-gray-400" />
                                Context & Generation
                            </h3>
                        </div>
                        
                        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-4">
                            {/* Character Assignment */}
                            <div className="glass-panel p-4 rounded-xl border border-white/5">
                                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Character</h4>
                                {linkedCharacter ? (
                                    <div className="flex items-center gap-3 p-2 bg-gray-800/30 rounded-lg">
                                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 flex items-center justify-center shrink-0 overflow-hidden">
                                            {linkedCharacter.has_avatar ? (
                                                <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-full h-full object-cover" />
                                            ) : (
                                                <MessageSquare size={14} className="text-blue-400" />
                                            )}
                                        </div>
                                        <div className="min-w-0">
                                            <p className="text-sm text-gray-200 truncate">{linkedCharacter.name}</p>
                                            <p className="text-[10px] text-gray-500">Linked to this chat</p>
                                        </div>
                                    </div>
                                ) : (
                                    <p className="text-sm text-gray-500 text-center py-2 border border-dashed border-gray-700/50 rounded-lg">
                                        No character assigned
                                    </p>
                                )}
                            </div>

                            {/* Lorebooks */}
                            <div className="glass-panel p-4 rounded-xl border border-white/5">
                                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-2">
                                    <BookOpen size={14} /> Lorebooks
                                </h4>
                                {lorebooks.length === 0 ? (
                                    <p className="text-sm text-gray-500 text-center py-4 border border-dashed border-gray-700/50 rounded-lg">
                                        No lorebooks available
                                    </p>
                                ) : (
                                    <div className="space-y-2">
                                        {lorebooks.map(lb => {
                                            const isActive = selectedLorebooks.includes(lb.id);
                                            return (
                                                <button
                                                    key={lb.id}
                                                    onClick={() => toggleLorebook(lb.id)}
                                                    className={clsx(
                                                        "w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors",
                                                        isActive ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30" : "bg-gray-800/30 text-gray-400 hover:bg-white/5 border border-transparent"
                                                    )}
                                                >
                                                    {isActive ? <Check size={14} className="text-indigo-400 shrink-0" /> : <div className="w-3.5 h-3.5 rounded border border-gray-600 shrink-0" />}
                                                    <div className="min-w-0">
                                                        <p className="truncate font-medium">{lb.name}</p>
                                                        {lb.description && <p className="text-[10px] text-gray-500 truncate">{lb.description}</p>}
                                                    </div>
                                                </button>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>

                            {/* Active context info */}
                            {selectedLorebooks.length > 0 && (
                                <div className="text-[11px] text-gray-500 px-1">
                                    {selectedLorebooks.length} lorebook{selectedLorebooks.length !== 1 ? 's' : ''} active. Lorebook context is injected into the AI's system prompt.
                                </div>
                            )}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            <ConfirmationModal
                isOpen={!!deleteTarget}
                onClose={() => setDeleteTarget(null)}
                onConfirm={handleDeleteChat}
                title="Delete Chat"
                message={`Are you sure you want to delete "${deleteTarget?.name || 'this chat'}"? All messages will be lost.`}
                confirmText="Delete"
                isDangerous
            />
        </motion.div>
    );
}
