import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, Send, Image as ImageIcon, Settings, PanelRightClose, PanelRightOpen, Paperclip, MoreVertical, Sparkles, Plus, Loader2, Trash2, Edit3, BookOpen, Check } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { useLocation } from 'react-router-dom';
import { useMessages, useChats, useSendMessage, useChat, useCreateChat, useDeleteChat, useLorebooks, useCharacters, useRenameChat, getAvatarUrl } from '../hooks/useWorldVault';
import { api } from '../api';
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
        if (!message.trim()) return;
        
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

        try {
            const res = await sendMessageMutation.mutateAsync({
                chatId: chatIdToUse,
                message: { role: 'user', content: msgContent, lorebook_ids: selectedLorebooks }
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

    const handleCreateChat = () => {
        createChatMutation.mutate({ name: 'New Chat' }, {
            onSuccess: (chat) => {
                setActiveChatId(chat.id);
                toast.success('New chat created');
            },
            onError: () => toast.error('Failed to create chat')
        });
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
            {/* Sidebar for Chats */}
            <div className="w-64 border-r border-white/5 bg-gray-900/60 hidden md:flex flex-col shrink-0">
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
                                        onClick={() => setActiveChatId(chat.id)}
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
                <div className="h-16 border-b border-white/5 flex items-center justify-between px-4 lg:px-6 shrink-0 bg-gray-900/40 backdrop-blur-md z-10">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center overflow-hidden">
                            {linkedCharacter?.has_avatar ? (
                                <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-full h-full object-cover" />
                            ) : (
                                <MessageSquare className="text-blue-400" size={20} />
                            )}
                        </div>
                        <div>
                            <h2 className="font-semibold text-gray-100 flex items-center gap-2">
                                {activeChat?.name || 'Roleplay Session'}
                                <span className="px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 text-[10px] font-bold uppercase tracking-wider border border-blue-500/20">
                                    Active
                                </span>
                            </h2>
                            <p className="text-xs text-gray-500">
                                {linkedCharacter ? `Playing as ${linkedCharacter.name}` : (activeChatId ? `Chat ID: ${activeChatId.slice(0, 8)}...` : 'No chat selected')}
                            </p>
                        </div>
                    </div>
                    
                    <div className="flex items-center gap-2">
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
                                            AI <Loader2 size={12} className="animate-spin" />
                                        </div>
                                        <div className="p-4 rounded-2xl whitespace-pre-wrap text-sm bg-gray-800/40 text-gray-200 border border-gray-700/50 rounded-tl-sm">
                                            {jobData.text + "..."}
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
                    <div className="max-w-4xl mx-auto relative group">
                        <textarea
                            value={message}
                            onChange={(e) => setMessage(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder="Type a message or use / to trigger commands..."
                            className="w-full bg-gray-900/80 border border-gray-700/50 rounded-2xl pl-12 pr-14 py-4 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50 transition-all resize-none shadow-inner"
                            rows={1}
                            style={{ minHeight: '60px', maxHeight: '200px' }}
                            disabled={sendMessageMutation.isPending}
                        />
                        <button className="absolute left-3 bottom-3 p-2 text-gray-400 hover:text-blue-400 transition-colors rounded-xl hover:bg-blue-500/10">
                            <Paperclip size={20} />
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
                            onClick={handleSendMessage}
                            disabled={!message.trim() || sendMessageMutation.isPending}
                            className={clsx(
                                "absolute right-2 bottom-3 p-2 transition-all rounded-xl",
                                message.trim() && !sendMessageMutation.isPending
                                    ? "bg-blue-600 text-white shadow-[0_0_15px_rgba(37,99,235,0.4)] hover:bg-blue-500 hover:scale-105" 
                                    : "bg-gray-800 text-gray-500 cursor-not-allowed"
                            )}
                        >
                            {sendMessageMutation.isPending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} className={message.trim() ? "translate-x-0.5 -translate-y-0.5" : ""} />}
                        </button>
                    </div>
                    <div className="max-w-4xl mx-auto mt-2 flex items-center justify-between px-2 text-[10px] text-gray-500">
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
                        className="hidden lg:flex flex-col border-l border-white/5 bg-gray-900/30 overflow-hidden shrink-0"
                    >
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
