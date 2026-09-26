import React, { useRef } from 'react';
import { Plus, MessageSquare, Edit3, Trash2, Loader2, Upload } from 'lucide-react';
import clsx from 'clsx';
import { getAvatarUrl } from '../../hooks/useWorldVault';

export default function ChatSidebar({
    chatsCollapsed,
    mobileTab,
    handleCreateChat,
    chatSearchQuery,
    setChatSearchQuery,
    setChatOffset,
    isChatsLoading,
    chats,
    activeChatList,
    renamingChatId,
    renameValue,
    setRenameValue,
    finishRename,
    setActiveChatId,
    setMobileTab,
    activeChatId,
    characters,
    startRename,
    handleDeleteChat,
    handleImportChatFile,
    isImportingChat,
    hasMoreChats,
    CHAT_PAGE_SIZE,
    setRenamingChatId
}) {
    const importInputRef = useRef(null);

    const onImportFilePicked = (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (file && handleImportChatFile) handleImportChatFile(file);
    };
    return (
        <div className={clsx(
            "flex-col shrink-0 border-b lg:border-r border-white/5 bg-gray-900 flex-1 lg:flex-none overflow-hidden min-w-0",
            "w-full",
            chatsCollapsed ? "lg:w-0 lg:border-r-0" : "lg:w-72",
            mobileTab === 'chats' ? "flex" : "hidden lg:flex"
        )}>
            <div className="h-12 lg:h-16 flex items-center justify-between px-4 border-b border-white/5 shrink-0">
                <h3 className="font-semibold text-gray-200 tracking-wide">Chats</h3>
                <div className="flex items-center gap-1">
                    <input
                        ref={importInputRef}
                        type="file"
                        accept=".jsonl,.json,application/x-ndjson,application/json"
                        className="hidden"
                        onChange={onImportFilePicked}
                    />
                    <button
                        onClick={() => importInputRef.current?.click()}
                        disabled={isImportingChat}
                        className="p-1.5 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors disabled:opacity-40"
                        title="Import chat (SillyTavern JSONL or app JSON)"
                    >
                        {isImportingChat ? <Loader2 size={18} className="animate-spin" /> : <Upload size={18} />}
                    </button>
                    <button
                        onClick={() => handleCreateChat()}
                        className="p-1.5 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                        title="New chat"
                    >
                        <Plus size={18} />
                    </button>
                </div>
            </div>

            <div className="px-3 py-2 border-b border-white/5 shrink-0">
                <input
                    type="text"
                    value={chatSearchQuery}
                    onChange={(e) => { setChatSearchQuery(e.target.value); setChatOffset(0); }}
                    placeholder="Search chats..."
                    className="w-full bg-gray-800/60 border border-white/5 rounded-lg px-3 py-1.5 text-xs text-gray-300 placeholder-gray-600 focus:outline-none focus:border-blue-500/40"
                />
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
                 ) : activeChatList?.map(chat => (
                    <div key={chat.id} className="relative group">
                        {renamingChatId === chat.id ? (
                            <div className="flex items-center gap-1 px-1">
                                <input
                                    autoFocus
                                    value={renameValue}
                                    onChange={e => setRenameValue(e.target.value)}
                                    onKeyDown={e => { if (e.key === 'Enter') finishRename(); if (e.key === 'Escape') setRenamingChatId(null); }}
                                    onBlur={finishRename}
                                    aria-label="Chat name"
                                    placeholder="Chat name"
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
                                    <button onClick={e => { e.stopPropagation(); startRename(chat); }} aria-label="Rename chat" className="p-1 min-w-6 min-h-6 inline-flex items-center justify-center hover:text-white text-gray-500 rounded"><Edit3 size={11} /></button>
                                    <button onClick={e => { e.stopPropagation(); handleDeleteChat(chat); }} aria-label="Delete chat" className="p-1 min-w-6 min-h-6 inline-flex items-center justify-center hover:text-red-400 text-gray-500 rounded"><Trash2 size={11} /></button>
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
    );
}
