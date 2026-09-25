import React, { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import clsx from 'clsx';
import { useSearchParams } from 'react-router-dom';
import { MessageSquare, Activity, Settings, ImageIcon, X, GitBranch, Volume2 } from 'lucide-react';
import { settingsApi, TTS_ENABLE_PAYLOAD } from '../api/settingsApi';
import { useUpdateSettings } from '../store/settingsStore';
import SceneGallery from '../components/SceneGallery';
import BottomTabBar from '../components/BottomTabBar';
import NewChatModal from '../components/chat/NewChatModal';
import GreetingPickerModal from '../components/chat/GreetingPickerModal';
import CharacterDetailsModal from '../components/chat/CharacterDetailsModal';
import ChatSidebar from '../components/chat/ChatSidebar';
import ChatWorkspaceHeader from '../components/chat/ChatWorkspaceHeader';
import ChatInputContainer from '../components/chat/ChatInputContainer';
import ChatContextPanel from '../components/chat/ChatContextPanel';
import ChatTimeline from '../components/chat/ChatTimeline';
import MessageTimeline from '../components/chat/MessageTimeline';
import { ChatWorkspaceProvider, useChatWorkspace } from '../contexts/ChatWorkspaceContext';

export default function ChatWorkspace() {
    return (
        <ChatWorkspaceProvider>
            <ChatWorkspaceLayout />
        </ChatWorkspaceProvider>
    );
}

function ChatWorkspaceLayout() {
    const context = useChatWorkspace();
    const [searchParams, setSearchParams] = useSearchParams();
    const { updateSetting } = useUpdateSettings();
    const ttsEnabled = context.settings?.ai?.ttsEnabled;
    const [ttsBannerDismissed, setTtsBannerDismissed] = useState(false);

    const enableTtsMutation = useMutation({
        mutationFn: () => settingsApi.update(TTS_ENABLE_PAYLOAD),
        onError: () => {
            // Store update still stands; backend sync failure is non-fatal.
        }
    });

    const handleEnableTts = () => {
        updateSetting('ai', 'ttsEnabled', true);
        enableTtsMutation.mutate();
    };
    const {
        mobileTab, setMobileTab,
        activeChatId, messages, setMessageSearch,
        setTimelineVisible, listContainerRef,
        showNewChatModal, characters, lorebooks, personas: personasCtx = [], confirmCreateChat, setShowNewChatModal,
        showCharacterDetails, linkedCharacter, setShowCharacterDetails,
        greetingModal, setGreetingModal, hasCreatedChatRef,
        showScenesModal, setShowScenesModal, sceneTab, setSceneTab, chatImages,
        chatCollection, handleSaveImageToCollection, collectionsList,
        avatarModalSrc, setAvatarModalSrc, contextCollapsed,
        timelineVisible, activeBranch, setActiveBranch
    } = context;

    useEffect(() => {
        if (searchParams.get('new') === '1') {
            setShowNewChatModal(true);
            setSearchParams({}, { replace: true });
        }
    }, [searchParams, activeChatId, setShowNewChatModal, setSearchParams]);

    useEffect(() => {
        const onKeyDown = (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') {
                const target = e.target;
                const typing =
                    target instanceof HTMLElement &&
                    (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);
                if (typing) return;
                e.preventDefault();
                setShowNewChatModal(true);
            }
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [setShowNewChatModal]);

    return (
        <motion.div 
            className="h-full flex flex-col bg-[#0B0E14] overflow-hidden font-sans"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
        >
            <div className="flex flex-1 flex-row min-h-0 overflow-hidden">
                <ChatSidebar {...context} />
                
                <div className={clsx("flex-col min-w-0 bg-[#0B0E14] relative flex-1 lg:flex-auto", mobileTab === 'chat' ? "flex" : "hidden lg:flex")}>
                    <ChatWorkspaceHeader
                        {...context}
                        onSearchChange={(q) => setMessageSearch(q)}
                    />

                    <AnimatePresence>
                        {!ttsEnabled && !ttsBannerDismissed && (
                            <motion.div
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: 'auto' }}
                                exit={{ opacity: 0, height: 0 }}
                                className="px-3 sm:px-4 lg:px-6 pt-3"
                            >
                                <div className="flex items-center gap-3 rounded-xl border border-purple-500/30 bg-purple-500/10 px-4 py-2.5">
                                    <Volume2 size={16} className="text-purple-300 shrink-0" />
                                    <span className="flex-1 text-sm text-purple-100">
                                        Enable voice narration to hear character replies read aloud.
                                    </span>
                                    <button
                                        onClick={handleEnableTts}
                                        className="px-3 py-1.5 text-xs font-medium rounded-lg bg-purple-500/30 text-purple-100 hover:bg-purple-500/40 transition-colors"
                                    >
                                        Enable voice
                                    </button>
                                    <button
                                        onClick={() => setTtsBannerDismissed(true)}
                                        aria-label="Dismiss voice narration banner"
                                        className="p-1.5 text-purple-200/70 hover:text-white rounded-lg hover:bg-white/10 transition-colors"
                                    >
                                        <X size={14} />
                                    </button>
                                </div>
                            </motion.div>
                        )}
                    </AnimatePresence>

                    <div className="flex-1 overflow-y-auto p-3 sm:p-4 lg:p-6 custom-scrollbar" ref={listContainerRef}>
                        {!activeChatId && messages.length === 0 ? (
                            <div className="h-full flex flex-col items-center justify-center text-center px-4">
                                <div className="w-16 h-16 sm:w-20 sm:h-20 bg-gray-800/50 rounded-2xl flex items-center justify-center mb-4 sm:mb-6 shadow-xl border border-white/5">
                                    <MessageSquare size={32} className="text-gray-500" />
                                </div>
                                <h3 className="text-xl sm:text-2xl font-bold text-gray-200 mb-2 sm:mb-3">Welcome to Roleplay</h3>
                                <p className="text-sm sm:text-base text-gray-400 max-w-sm mx-auto mb-6 sm:mb-8 leading-relaxed">
                                    Select a chat or create a new one to begin your roleplay.
                                </p>
                            </div>
                        ) : (
                            <MessageTimeline />
                        )}
                    </div>
                    
                    <ChatInputContainer {...context} />
                </div>
                
                <div className={clsx(
                    "flex-col shrink-0 border-l border-white/5 bg-gray-900 lg:bg-gray-900/70 flex-1 lg:flex-none overflow-hidden min-w-0",
                    "w-full",
                    contextCollapsed ? "lg:w-0 lg:border-l-0" : "lg:w-72",
                    mobileTab === 'context' ? "flex" : "hidden lg:flex"
                )}>
                    <div className="h-12 lg:h-16 border-b border-white/5 flex items-center justify-between px-4 shrink-0 bg-gray-900/60 backdrop-blur-md">
                        <h3 className="font-semibold text-gray-200 flex items-center gap-2 text-sm">
                            <Settings size={14} className="text-gray-400" />
                            Context & Settings
                        </h3>
                        <button
                            onClick={() => setMobileTab('chat')}
                            aria-label="Close context panel"
                            className="lg:hidden p-2 -mr-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/10"
                        >
                            <X size={18} />
                        </button>
                    </div>
                    <div className="flex-1 overflow-y-auto custom-scrollbar relative bg-gray-900/40">
                        {activeChatId ? (
                            <ChatContextPanel activeChatId={activeChatId} />
                        ) : (
                            <div className="p-6 text-center text-sm text-gray-500">
                                Select a chat to view context
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* === TIMELINE PANEL (Overlay on desktop) === */}
            <AnimatePresence>
                {timelineVisible && (
                    <motion.div
                        initial={{ x: 360, opacity: 0 }}
                        animate={{ x: 0, opacity: 1 }}
                        exit={{ x: 360, opacity: 0 }}
                        transition={{ duration: 0.3, ease: 'easeInOut' }}
                        className="fixed lg:absolute inset-y-0 right-0 z-40 w-80 bg-gray-900 border-l border-white/10 overflow-hidden flex flex-col"
                    >
                        <div className="h-14 border-b border-white/5 flex items-center justify-between px-4 shrink-0 bg-gray-900/60 backdrop-blur-md">
                            <h3 className="font-semibold text-gray-200 flex items-center gap-2 text-sm">
                                <GitBranch size={14} className="text-gray-400" />
                                Branch Timeline
                            </h3>
                            <button
                                onClick={() => setTimelineVisible(false)}
                                className="p-2 text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors"
                                title="Close timeline"
                            >
                                <X size={16} />
                            </button>
                        </div>
                        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
                            {activeChatId && (
                                <ChatTimeline
                                    chatId={activeChatId}
                                    activeBranch={activeBranch}
                                    onBranchChange={(branchId) => {
                                        setActiveBranch(branchId);
                                        setTimelineVisible(false);
                                    }}
                                    onNewBranch={(data) => {
                                        setActiveBranch(data.branch_id);
                                    }}
                                />
                            )}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            <AnimatePresence>
                {showNewChatModal && (
                    <NewChatModal
                        characters={characters}
                        lorebooks={lorebooks}
                        personas={personasCtx}
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
                        onClose={() => { setGreetingModal(null); if(hasCreatedChatRef) hasCreatedChatRef.current = false; }}
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
                            <button type="button" aria-label="Close scenes gallery" onClick={() => setShowScenesModal(false)} className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                                <X size={18} />
                            </button>
                        </div>
                        <div className="flex gap-2 px-6 pt-4 shrink-0">
                            <button
                                onClick={() => setSceneTab('chat')}
                                className={clsx('px-4 py-1.5 rounded-xl text-xs font-medium transition-colors', sceneTab === 'chat' ? 'bg-purple-500/20 text-purple-300' : 'bg-gray-800/60 text-gray-400 hover:text-gray-200')}
                            >
                                This chat ({chatImages?.length || 0})
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
                                    images={chatImages?.map(img => img.path) || []}
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
                                            {collectionsList?.map(c => (
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
