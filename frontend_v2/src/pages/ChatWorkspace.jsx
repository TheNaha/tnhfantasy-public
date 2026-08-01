import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, Send, Image as ImageIcon, Settings, PanelRightClose, PanelRightOpen, Paperclip, MoreVertical, Sparkles, Plus, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import { useMessages, useChats, useSendMessage, useChat, useCreateChat } from '../hooks/useWorldVault';
import { useWorldVaultStore } from '../store/worldVaultStore';
import { useWebSocket, EventTypes } from '../api/websocket';

export default function ChatWorkspace() {
    const [isRightPanelOpen, setIsRightPanelOpen] = useState(true);
    const [message, setMessage] = useState('');
    const messagesEndRef = useRef(null);

    const activeChatId = useWorldVaultStore(state => state.activeChatId);
    const setActiveChatId = useWorldVaultStore(state => state.setActiveChat);
    const updateStreamingJob = useWorldVaultStore(state => state.updateStreamingJob);
    const streamingJobs = useWorldVaultStore(state => state.streamingJobs);

    const { data: chats, isLoading: isChatsLoading } = useChats();
    const { data: activeChat } = useChat(activeChatId);
    const { data: messages = [], isLoading: isMessagesLoading } = useMessages(activeChatId);
    
    const sendMessageMutation = useSendMessage();
    const createChatMutation = useCreateChat();

    // WebSocket for streaming updates
    const { subscribe } = useWebSocket();

    useEffect(() => {
        // If we have chats but no active chat, select the first one
        if (chats?.length > 0 && !activeChatId) {
            setActiveChatId(chats[0].id);
        }
    }, [chats, activeChatId, setActiveChatId]);

    useEffect(() => {
        const unsubProgress = subscribe(EventTypes.JOB_PROGRESS, (event) => {
            const job = event.data?.job || event;
            const streamText = job.metadata_?.text || job.output?.text || job.progress_text;
            if (streamText && job.metadata_?.chat_id === activeChatId) {
                updateStreamingJob(job.id, { text: streamText, status: job.status });
            }
        });
        
        const unsubCompleted = subscribe(EventTypes.JOB_COMPLETED, (event) => {
             const job = event.data?.job || event;
             if (job.metadata_?.chat_id === activeChatId) {
                 // The message should be refetched by react-query via some event, but we'll let real-time handle it
             }
        });

        return () => {
            unsubProgress();
            unsubCompleted();
        };
    }, [subscribe, activeChatId, updateStreamingJob]);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, streamingJobs]);

    const handleSendMessage = async () => {
        if (!message.trim()) return;
        
        let chatIdToUse = activeChatId;
        if (!chatIdToUse) {
            const newChat = await createChatMutation.mutateAsync({ name: 'New Chat' });
            chatIdToUse = newChat.id;
            setActiveChatId(newChat.id);
        }

        const msgContent = message.trim();
        setMessage('');

        try {
            const res = await sendMessageMutation.mutateAsync({
                chatId: chatIdToUse,
                message: { role: 'user', content: msgContent }
            });
            if (res.job_id) {
                updateStreamingJob(res.job_id, { text: '', status: 'running' });
            }
        } catch (error) {
            console.error('Failed to send message:', error);
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSendMessage();
        }
    };

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
                    <button 
                        onClick={() => {
                            createChatMutation.mutate({ name: 'New Chat' }, {
                                onSuccess: (chat) => setActiveChatId(chat.id)
                            });
                        }}
                        className="p-1.5 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                    >
                        <Plus size={18} />
                    </button>
                </div>
                <div className="flex-1 overflow-y-auto p-2 space-y-1">
                    {isChatsLoading ? (
                        <div className="flex justify-center p-4"><Loader2 className="animate-spin text-gray-500" /></div>
                    ) : (
                        chats?.map(chat => (
                            <button
                                key={chat.id}
                                onClick={() => setActiveChatId(chat.id)}
                                className={clsx(
                                    "w-full text-left px-3 py-2 rounded-lg text-sm transition-colors",
                                    activeChatId === chat.id ? "bg-blue-500/20 text-blue-300" : "text-gray-400 hover:bg-white/5"
                                )}
                            >
                                {chat.name || 'Unnamed Chat'}
                            </button>
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
                            <MessageSquare className="text-blue-400" size={20} />
                        </div>
                        <div>
                            <h2 className="font-semibold text-gray-100 flex items-center gap-2">
                                {activeChat?.name || 'Roleplay Session'}
                                <span className="px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 text-[10px] font-bold uppercase tracking-wider border border-blue-500/20">
                                    Active
                                </span>
                            </h2>
                            <p className="text-xs text-gray-500">
                                {activeChatId ? `Chat ID: ${activeChatId.slice(0, 8)}...` : 'No chat selected'}
                            </p>
                        </div>
                    </div>
                    
                    <div className="flex items-center gap-2">
                        <button className="p-2 text-gray-400 hover:text-gray-200 hover:bg-white/5 rounded-lg transition-colors">
                            <MoreVertical size={20} />
                        </button>
                        <button 
                            onClick={() => setIsRightPanelOpen(!isRightPanelOpen)}
                            className="p-2 text-gray-400 hover:text-gray-200 hover:bg-white/5 rounded-lg transition-colors hidden lg:flex"
                            title="Toggle Generator Panel"
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
                            <h3 className="text-lg font-medium text-gray-300">Welcome to the Story Sandbox</h3>
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
                                    <div className="text-xs text-gray-500 mb-1 ml-1">{msg.role === 'user' ? 'You' : 'AI'}</div>
                                    <div className={clsx(
                                        "p-4 rounded-2xl whitespace-pre-wrap text-sm",
                                        msg.role === 'user' 
                                            ? "bg-blue-600/20 text-blue-100 border border-blue-500/20 rounded-tr-sm" 
                                            : "bg-gray-800/40 text-gray-200 border border-gray-700/50 rounded-tl-sm"
                                    )}>
                                        {msg.content}
                                    </div>
                                </div>
                            ))}
                            
                            {/* Render active streaming jobs */}
                            {Object.entries(streamingJobs).map(([jobId, jobData]) => (
                                jobData.status === 'running' && (
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
                            onClick={handleSendMessage}
                            disabled={!message.trim() || sendMessageMutation.isPending}
                            className={clsx(
                                "absolute right-3 bottom-3 p-2 transition-all rounded-xl",
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
                        <div className="flex gap-4">
                            <span className="flex items-center gap-1"><Sparkles size={12} /> Auto-Gen: On</span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Right Panel: Generator / Context Parameters */}
            <AnimatePresence initial={false}>
                {isRightPanelOpen && (
                    <motion.div
                        initial={{ width: 0, opacity: 0 }}
                        animate={{ width: 400, opacity: 1 }}
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
                        
                        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
                            <div className="space-y-6">
                                {/* Section 1 */}
                                <div className="glass-panel p-4 rounded-xl border border-white/5">
                                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                                        <ImageIcon size={14} /> Image Generation
                                    </h4>
                                    <p className="text-sm text-gray-500 mb-4">
                                        The AI will automatically generate images when describing scenes or actions.
                                    </p>
                                    <div className="space-y-3">
                                        <label className="flex items-center justify-between cursor-pointer">
                                            <span className="text-sm text-gray-300">Auto-Generate</span>
                                            <div className="relative inline-block w-10 mr-2 align-middle select-none">
                                                <input type="checkbox" className="toggle-checkbox absolute block w-5 h-5 rounded-full bg-white border-4 appearance-none cursor-pointer transition-transform duration-200 ease-in-out" defaultChecked />
                                                <label className="toggle-label block overflow-hidden h-5 rounded-full bg-blue-500 cursor-pointer"></label>
                                            </div>
                                        </label>
                                    </div>
                                </div>
                                
                                {/* Section 2 */}
                                <div className="glass-panel p-4 rounded-xl border border-white/5">
                                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-4">Lorebooks</h4>
                                    <div className="text-sm text-gray-500 text-center py-4 border border-dashed border-gray-700/50 rounded-lg">
                                        No active lorebooks
                                    </div>
                                </div>
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.div>
    );
}
