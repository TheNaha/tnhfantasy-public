import React, { useState } from 'react';
import {
    PanelLeftOpen, PanelLeftClose, PanelRightOpen, MessageSquare, Sparkles,
    Loader2, Clock, MapPin, Download, FileJson, BookOpen, GitBranch, Search,
    X, UserPlus, Users, Tv
} from 'lucide-react';
import clsx from 'clsx';
import { getAvatarUrl } from '../../hooks/useWorldVault';
import CompanionPickerModal from './CompanionPickerModal';

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
    handleExportToStory,
    exportToStoryMutation,
    messages,
    setTimelineVisible,
    contextCollapsed,
    setContextCollapsed,
    onSearchChange,
    characters = [],
    targetCharacterId = '',
    setTargetCharacterId,
    handleChatUpdate,
    onToggleStageMode,
    isStageMode = false,
}) {
    const [showCompanionModal, setShowCompanionModal] = useState(false);
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
                {/* Companion & Character Roster Tray */}
                <div className="flex items-center -space-x-1.5 sm:space-x-1 shrink-0">
                    {/* Primary Character Avatar */}
                    <button
                        type="button"
                        aria-label={linkedCharacter?.name ? `View ${linkedCharacter.name}'s avatar` : 'View avatar'}
                        onClick={() => {
                            if (setTargetCharacterId) setTargetCharacterId('');
                            if (linkedCharacter?.avatar_path) handleAvatarClick(getAvatarUrl(linkedCharacter.id));
                        }}
                        className={clsx(
                            "w-8 h-8 sm:w-9 sm:h-9 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border flex items-center justify-center shrink-0 overflow-hidden transition-all",
                            (!targetCharacterId || targetCharacterId === linkedCharacter?.id)
                                ? "ring-2 ring-blue-500/80 border-blue-400 scale-105 z-10"
                                : "border-white/10 opacity-75 hover:opacity-100"
                        )}
                        title={linkedCharacter ? `${linkedCharacter.name} (Primary Character — Click to target)` : 'Primary Character'}
                    >
                        {linkedCharacter?.avatar_path
                            ? <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-full h-full object-cover" />
                            : <MessageSquare className="text-blue-400" size={15} />
                        }
                    </button>

                    {/* Additional Companion Avatars */}
                    {activeChat?.additional_character_ids?.map((companionId) => {
                        const companion = characters.find(c => c.id === companionId);
                        if (!companion) return null;
                        const isTargeted = targetCharacterId === companion.id;
                        return (
                            <button
                                key={companion.id}
                                type="button"
                                onClick={() => setTargetCharacterId?.(isTargeted ? '' : companion.id)}
                                className={clsx(
                                    "w-8 h-8 sm:w-9 sm:h-9 rounded-full bg-gray-800 border flex items-center justify-center shrink-0 overflow-hidden transition-all",
                                    isTargeted
                                        ? "ring-2 ring-purple-500 border-purple-400 scale-105 z-10"
                                        : "border-white/10 opacity-75 hover:opacity-100"
                                )}
                                title={`${companion.name} (Companion — Click to target)`}
                            >
                                {companion.avatar_path ? (
                                    <img src={getAvatarUrl(companion.id)} alt={companion.name} className="w-full h-full object-cover" />
                                ) : (
                                    <span className="text-3xs font-bold text-gray-300">{companion.name.charAt(0)}</span>
                                )}
                            </button>
                        );
                    })}

                    {/* Add Companion Button */}
                    {activeChatId && (
                        <button
                            type="button"
                            onClick={() => setShowCompanionModal(true)}
                            className="w-7 h-7 sm:w-8 sm:h-8 rounded-full border border-dashed border-white/20 hover:border-blue-400/60 bg-white/5 hover:bg-blue-500/10 text-gray-400 hover:text-blue-300 flex items-center justify-center transition-all ml-1 shrink-0"
                            title="Manage companions in party"
                        >
                            <UserPlus size={13} />
                        </button>
                    )}
                </div>
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
                            aria-label="Search messages" placeholder="Search messages..."
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
                {activeChat?.id && (
                    <div
                        className={clsx(
                            "px-2.5 py-1 rounded text-2xs font-medium flex items-center gap-1.5 shadow-sm border",
                            activeChat.director_enabled !== false
                                ? "bg-emerald-500/10 border-emerald-500/25 text-emerald-300"
                                : "bg-gray-800/50 border-white/5 text-gray-400"
                        )}
                        title={
                            activeChat.director_enabled !== false
                                ? `System 1 Director Active${activeChat.state_snapshot?.scene_tension_label ? ` • Tension: ${activeChat.state_snapshot.scene_tension}/5 (${activeChat.state_snapshot.scene_tension_label})` : ''}${activeChat.state_snapshot?.character_mood ? ` • Mood: ${activeChat.state_snapshot.character_mood}` : ''}`
                                : 'System 1 Director Paused'
                        }
                    >
                        <Sparkles size={11} className={activeChat.director_enabled !== false ? "text-emerald-400" : "text-gray-500"} />
                        <span>
                            {activeChat.director_enabled !== false
                                ? `Director${activeChat.state_snapshot?.scene_tension ? ` • T${activeChat.state_snapshot.scene_tension}/5` : ''}`
                                : 'Director Off'}
                        </span>
                        {activeChat.state_snapshot?.character_mood && (
                            <span className="text-emerald-200/80 max-w-[90px] truncate">
                                · {activeChat.state_snapshot.character_mood}
                            </span>
                        )}
                    </div>
                )}
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
                onClick={handleExportToStory}
                disabled={!activeChatId || !messages.length || exportToStoryMutation?.isPending}
                className="p-2 text-indigo-400 hover:text-indigo-200 rounded-xl hover:bg-indigo-500/10 transition-colors disabled:opacity-30 disabled:cursor-not-allowed hidden lg:block"
                title="Export chat to Story Sandbox"
            >
                {exportToStoryMutation?.isPending ? <Loader2 size={18} className="animate-spin" /> : <BookOpen size={18} />}
            </button>
            {onToggleStageMode && (
                <button
                    onClick={onToggleStageMode}
                    className={clsx(
                        "p-2 rounded-xl transition-colors shrink-0 hidden sm:flex",
                        isStageMode ? "text-purple-300 bg-purple-500/20 border border-purple-500/30" : "text-gray-400 hover:text-white hover:bg-white/5"
                    )}
                    title={isStageMode ? "Exit Stage Mode" : "Enter Visual Novel Stage Mode"}
                >
                    <Tv size={18} />
                </button>
            )}
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

            <CompanionPickerModal
                isOpen={showCompanionModal}
                onClose={() => setShowCompanionModal(false)}
                characters={characters}
                primaryCharacterId={linkedCharacter?.id}
                additionalCharacterIds={activeChat?.additional_character_ids || []}
                onSave={(ids) => handleChatUpdate?.({ additional_character_ids: ids })}
            />
        </div>
    );
}
