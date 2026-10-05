import React from 'react';
import { X, ImageIcon, Loader2, Paperclip, MoreHorizontal, Palette, Wand2, BookOpen, Ghost, Sparkles, Send } from 'lucide-react';
import clsx from 'clsx';
import CommandPalette from './CommandPalette';
import StreamingInput from './StreamingInput';
import TokenMeter from './TokenMeter';

export default function ChatInputContainer({
    pendingAttachment, setPendingAttachment, activeChat, targetCharacterId,
    setTargetCharacterId, characters, message, activeCommand, setActiveCommand,
    setMessage, handleSuggestClick, fileInputRef, handleAttachmentChange,
    textareaRef, handleTextChange, handleKeyDown, activeChatId,
    sendMessageMutation, isUploading, showMoreTools, setShowMoreTools,
    handleGenerateScene, isGeneratingScene, handleIllustrate, illustrateMutation,
    agenticMode, setAgenticMode, narrateMode, setNarrateMode,
    handleImpersonate, impersonateMutation, suggestReplyMutation, suggestJobId,
    handleSendMessage, canSend
}) {
    return (
        <div className="px-3 sm:px-4 lg:px-6 py-3 sm:py-4 pb-4 border-t border-white/5 bg-gray-900/40 backdrop-blur-md shrink-0">
            <div className="max-w-4xl mx-auto">
                {pendingAttachment && (
                    <div className="mb-2 flex items-center gap-2 px-3 py-2 bg-blue-500/10 border border-blue-500/20 rounded-xl text-sm text-blue-300">
                        <ImageIcon size={13} className="shrink-0" />
                        <span className="truncate flex-1 text-xs">{pendingAttachment.name}</span>
                        <button onClick={() => setPendingAttachment(null)} aria-label={`Remove attachment ${pendingAttachment.name}`} className="p-1 min-w-6 min-h-6 inline-flex items-center justify-center hover:text-red-400 transition-colors shrink-0">
                            <X size={13} />
                        </button>
                    </div>
                )}
                <div className="relative">
                    {activeChat?.additional_character_ids?.length > 0 && (
                        <div className="absolute -top-10 right-0 flex items-center gap-2 bg-gray-900/80 backdrop-blur border border-gray-700 rounded-lg px-2 py-1 shadow-xl">
                            <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">Reply as:</span>
                            <select
                                value={targetCharacterId}
                                onChange={(e) => setTargetCharacterId(e.target.value)}
                                className="bg-transparent text-xs text-blue-300 font-medium focus:outline-none appearance-none cursor-pointer"
                            >
                                <option value="">{activeChat.character_id ? characters.find(c => c.id === activeChat.character_id)?.name || 'Default' : 'Default'}</option>
                                {activeChat.additional_character_ids.map(id => {
                                    const c = characters.find(char => char.id === id);
                                    return c ? <option key={c.id} value={c.id}>{c.name}</option> : null;
                                })}
                            </select>
                            <div className="pointer-events-none text-gray-500">
                                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
                            </div>
                        </div>
                    )}
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
                    <input ref={fileInputRef} type="file" aria-label="Attach image" accept="image/*" onChange={handleAttachmentChange} className="sr-only" />
                    
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

                        <div className="hidden sm:flex items-center gap-1">
                            <button
                                onClick={handleGenerateScene}
                                disabled={isGeneratingScene || !activeChatId}
                                className="p-1.5 sm:p-2 text-gray-400 hover:text-green-400 transition-colors rounded-xl hover:bg-green-500/10 disabled:opacity-50"
                                title="Generate Scene"
                            >
                                {isGeneratingScene ? <Loader2 size={18} className="animate-spin" /> : <ImageIcon size={18} />}
                            </button>
                            <button
                                onClick={handleIllustrate}
                                disabled={illustrateMutation.isPending || !activeChatId}
                                className={clsx(
                                    "p-1.5 sm:p-2 transition-colors rounded-xl",
                                    illustrateMutation.isPending
                                        ? "text-pink-400 bg-pink-500/10 cursor-not-allowed"
                                        : (activeChatId ? "text-gray-400 hover:text-pink-400 hover:bg-pink-500/10" : "text-gray-600 cursor-not-allowed")
                                )}
                                title="Illustrate moment"
                            >
                                {illustrateMutation.isPending ? <Loader2 size={18} className="animate-spin" /> : <Palette size={18} />}
                            </button>
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
                            <button
                                onClick={() => setNarrateMode(!narrateMode)}
                                className={clsx(
                                    "p-1.5 sm:p-2 transition-colors rounded-xl",
                                    narrateMode
                                        ? "text-purple-400 hover:text-purple-300 hover:bg-purple-500/10"
                                        : "text-gray-500 hover:text-gray-400 hover:bg-white/5"
                                )}
                                title={narrateMode ? "Narrate ON" : "Narrate OFF"}
                            >
                                <BookOpen size={18} />
                            </button>
                            <button
                                onClick={() => handleImpersonate()}
                                disabled={!activeChatId || impersonateMutation.isPending}
                                className={clsx(
                                    "p-1.5 sm:p-2 transition-all rounded-xl",
                                    impersonateMutation.isPending
                                        ? "text-purple-400 bg-purple-500/10 cursor-not-allowed"
                                        : (activeChatId ? "text-gray-400 hover:text-purple-400 hover:bg-purple-500/10" : "text-gray-600 cursor-not-allowed")
                                )}
                                title="Impersonate"
                            >
                                {impersonateMutation.isPending
                                    ? <Loader2 size={16} className="animate-spin" />
                                    : <Ghost size={16} />}
                            </button>
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
                        
                        <div className="flex items-center">
                            <TokenMeter text={message} />
                            <button
                                onClick={handleSendMessage}
                                disabled={!canSend}
                                aria-label="Send message"
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
                </div>
                <div className="mt-1.5 hidden sm:flex items-center justify-between px-1 text-xs text-gray-600">
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
    );
}
