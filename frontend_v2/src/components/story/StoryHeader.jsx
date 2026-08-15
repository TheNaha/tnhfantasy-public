import React from 'react';
import { BookOpen, Sparkles, Loader2, Save, Edit3, Book, Layers, ImageIcon, Download } from 'lucide-react';
import clsx from 'clsx';

export default React.memo(function StoryHeader({
    activeStory,
    activeChapter,
    activeChapterId,
    isGeneratingTitle,
    onAutoGenerateTitle,
    isSaving,
    onSave,
    isStreaming,
    isPreviewMode,
    onTogglePreview,
    isPanelOpen,
    onTogglePanel,
    mobileTab,
    onOpenContextMobile,
    onTitleChange,
    onExport,
}) {
    return (
        <div className="h-16 border-b border-white/5 flex items-center justify-between px-2 sm:px-6 bg-gray-900/60 backdrop-blur-md z-10 shrink-0 gap-2">
            <div className="flex items-center gap-1 sm:gap-3 min-w-0 flex-1">
                <div className="md:hidden p-1.5 sm:p-2 text-gray-500">
                    <BookOpen size={20} />
                </div>
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-500/20 border border-white/10 hidden sm:flex items-center justify-center shrink-0">
                    <BookOpen className="text-indigo-400" size={20} />
                </div>
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 min-w-0">
                        <input
                            type="text"
                            defaultValue={activeStory?.title || ''}
                            onBlur={onTitleChange}
                            className="bg-transparent font-semibold text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 rounded px-1 transition-all w-full truncate text-sm sm:text-base"
                        />
                    </div>
                    <div className="flex items-center gap-1 sm:gap-2 px-1 min-w-0">
                        <div className="flex flex-col min-w-0">
                            <p className="font-bold text-sm sm:text-base text-gray-200 truncate flex items-center gap-2">
                                {activeChapter ? `${activeChapter.title || `Chapter ${activeChapter.chapter_number}`}` : 'Select a chapter'}
                                {activeStory?.genre && <span className="hidden sm:inline font-normal text-xs text-gray-500">· {activeStory.genre}</span>}
                            </p>
                        </div>
                        {activeChapter && (
                            <button 
                                onClick={onAutoGenerateTitle} 
                                disabled={isGeneratingTitle}
                                className="text-[10px] bg-indigo-500/10 text-indigo-400 px-1.5 py-0.5 rounded hover:bg-indigo-500/20 transition-colors flex items-center gap-1 disabled:opacity-50 shrink-0"
                                title="Auto-generate chapter title using AI"
                            >
                                {isGeneratingTitle ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
                                <span className="hidden sm:inline">Auto Title</span>
                            </button>
                        )}
                    </div>
                </div>
            </div>
            
            <div className="flex items-center gap-1 sm:gap-2 shrink-0">
                {activeChapterId && (
                    <button
                        onClick={onSave}
                        disabled={isStreaming || isSaving}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-green-500/20 text-green-300 rounded-lg hover:bg-green-500/30 transition-colors disabled:opacity-30"
                        title="Save chapter content"
                    >
                        {isSaving ? <Loader2 size={12} className="animate-spin" /> : <Save size={14} />}
                        Save
                    </button>
                )}
                {onExport && activeStory && (
                    <button
                        onClick={onExport}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-500/20 text-blue-300 rounded-lg hover:bg-blue-500/30 transition-colors"
                        title="Export story as JSON"
                    >
                        <Download size={14} />
                        <span className="hidden sm:inline">Export</span>
                    </button>
                )}
                        <button
                            onClick={onTogglePreview}
                            className={clsx(
                                "p-1.5 sm:p-2 rounded-lg transition-colors border",
                                isPreviewMode ? "bg-purple-500/20 text-purple-400 border-purple-500/30" : "bg-white/5 text-gray-400 border-white/5 hover:text-white hover:bg-white/10"
                            )}
                            title={isPreviewMode ? "Edit Mode" : "Preview Mode"}
                        >
                            {isPreviewMode ? <Edit3 size={16} /> : <Book size={16} />}
                        </button>
                <button
                    onClick={onOpenContextMobile}
                    aria-label="Open context panel"
                    title="Context panel"
                    className={clsx(
                        "p-2 rounded-lg transition-colors border flex lg:hidden",
                        mobileTab === 'context' ? "bg-indigo-500/20 text-indigo-400 border-indigo-500/30" : "bg-white/5 text-gray-400 border-white/5 hover:text-white hover:bg-white/10"
                    )}
                >
                    <Layers size={20} />
                </button>
                <button
                    onClick={onTogglePanel}
                    aria-label="Toggle context panel"
                    title="Context panel"
                    className={clsx(
                        "p-2 rounded-lg transition-colors border hidden lg:flex",
                        isPanelOpen ? "bg-indigo-500/20 text-indigo-400 border-indigo-500/30" : "bg-white/5 text-gray-400 border-white/5 hover:text-white hover:bg-white/10"
                    )}
                >
                    <ImageIcon size={20} />
                </button>
            </div>
        </div>
    );
});
