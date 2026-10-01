import React, { useState } from 'react';
import { PanelLeftOpen, PanelLeftClose, PanelRightOpen, MessageSquare, Sparkles, Loader2, Clock, MapPin, Download, FileJson, GitBranch, Search, X } from 'lucide-react';
import clsx from 'clsx';
import { getAvatarUrl } from '../../hooks/useWorldVault';

export default function ChatWorkspaceHeader({
    chatsCollapsed,
    setChatsCollapsed,
    linkedCharacter,
    handleAvatarClick,
    activeChat,
    triggerAutoTitle,
    isGeneratingTitle,
    activeChatId,
    handleExportChat,
    handleExportChatJsonl,
    messages,
    setTimelineVisible,
    contextCollapsed,
    setContextCollapsed,
    onSearchChange,
}) {
    const [searchQuery, setSearchQuery] = useState('');
    const [searchOpen, setSearchOpen] = useState(false);

    const handleSearchToggle = () => {
        if (searchOpen) {
            setSearchQuery('');
            onSearchChange?.('');
        }
        setSearchOpen(!searchOpen);
    };

    const handleSearchInput = (e) => {
        const value = e.target.value;
        setSearchQuery(value);
        onSearchChange?.(value);
    };
    return (
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
                    aria-label={linkedCharacter?.name
                        ? `View ${linkedCharacter.name}'s avatar`
                        : 'View avatar'}
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
                            type="button"
                            onClick={triggerAutoTitle}
                            disabled={isGeneratingTitle}
                            className="text-xs bg-blue-500/10 text-blue-400 px-2 min-h-[24px] rounded hover:bg-blue-500/20 transition-colors inline-flex items-center gap-1 disabled:opacity-50 shrink-0"
                        >
                            {isGeneratingTitle ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
                            <span className="hidden sm:inline">Title</span>
                        </button>
                    </h2>
                    <p className="text-xs text-gray-500 truncate">
                        {linkedCharacter ? `${linkedCharacter.name}` : (activeChatId ? 'No character' : 'Select a chat')}
                        {activeChat?.persona_name && ` · as ${activeChat.persona_name}`}
                    </p>
                </div>
            </div>
            
            <div className="hidden md:flex items-center gap-2 mr-1 shrink-0">
                {searchOpen && (
                    <div className="relative">
                        <input
                            type="text"
                            value={searchQuery}
                            onChange={handleSearchInput}
                            placeholder="Search messages..."
                            className="w-40 lg:w-56 px-3 py-1.5 pl-8 bg-gray-800/80 border border-white/10 rounded-lg text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                            autoFocus
                        />
                        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
                    </div>
                )}
                <button
                    onClick={handleSearchToggle}
                    className={clsx(
                        "p-2 rounded-xl transition-colors shrink-0",
                        searchOpen ? "text-blue-400 bg-blue-500/10" : "text-gray-400 hover:text-white hover:bg-white/5"
                    )}
                    title={searchOpen ? 'Close search' : 'Search messages'}
                >
                    {searchOpen ? <X size={18} /> : <Search size={18} />}
                </button>
                {activeChat?.story_time && (
                    <div className="px-2.5 py-1 bg-gray-800/50 border border-white/5 rounded text-2xs font-medium text-gray-300 flex items-center gap-1.5 shadow-sm" title="Story Time">
                        <Clock size={12} className="text-indigo-400/70" /> 
                        <span className="max-w-[120px] truncate">{activeChat.story_time}</span>
                    </div>
                )}
                {activeChat?.story_location && (
                    <div className="px-2.5 py-1 bg-gray-800/50 border border-white/5 rounded text-2xs font-medium text-gray-300 flex items-center gap-1.5 shadow-sm" title="Story Location">
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
            <button
                onClick={handleExportChatJsonl}
                disabled={!activeChatId || !messages.length}
                className="p-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors disabled:opacity-30 disabled:cursor-not-allowed hidden lg:block"
                title="Export chat as SillyTavern-compatible JSONL"
            >
                <FileJson size={18} />
            </button>
            <button
                onClick={() => setTimelineVisible(true)}
                className="hidden lg:flex p-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors shrink-0"
                title="Show Branch Timeline"
            >
                <GitBranch size={18} />
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
    );
}
