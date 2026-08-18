import React from 'react';
import clsx from 'clsx';
import { Loader2, Wand2, ImageIcon, MessageSquare } from 'lucide-react';
import MessageItem from './MessageItem';
import TavernMessage from './TavernMessage';
import { getAvatarUrl } from '../../hooks/useWorldVault';
import { useVoices } from '../../hooks/useVoices';
import { useChatWorkspace } from '../../contexts/ChatWorkspaceContext';

export default function MessageTimeline() {
    const context = useChatWorkspace();
    const {
        messages, listItems, rowVirtualizer, linkedCharacter, activeChat,
        settings, handleEditMessage, handleDeleteMessage, handleRegenerate, handleRollback,
        handlePinMessage, handleSwipe, handleGenerateSwipe, handleAvatarClick,
        handleGenerateTTS, handleMessageIllustrate, hasMoreMessages, loadOlderMessages,
        messagesEndRef
    } = context;

    const { data: voices = [] } = useVoices();

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
                    onDelete={handleDeleteMessage}
                    onRegenerate={handleRegenerate}
                    onRollback={handleRollback}
                    onPin={handlePinMessage}
                    onSwipe={handleSwipe}
                    onGenerateSwipe={handleGenerateSwipe}
                    onAvatarClick={handleAvatarClick}
                     onGenerateTTS={handleGenerateTTS}
                    onIllustrate={handleMessageIllustrate}
                    ttsEnabled={settings.ai?.ttsEnabled}
                    voices={voices}
                    chatTtsVoiceId={activeChat?.tts_voice_id}
                    characterVoiceId={linkedCharacter?.voice_model_id}
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
    );
}