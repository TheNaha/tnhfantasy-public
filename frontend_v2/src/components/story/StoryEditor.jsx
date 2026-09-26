import React, { useCallback, useEffect, useRef } from 'react';
import { Sparkles } from 'lucide-react';
import MDEditor from '@uiw/react-md-editor';
import MentionPicker from './MentionPicker';

export default React.memo(function StoryEditor({ isPreviewMode, editorContent, onEditorChange, textareaRef, isStreaming, activeChapterId, wordCount, readingTimeMinutes, wordCountGoal }) {
    // Restoring the caret after a mention insert has to wait a macrotask: the
    // controlled <textarea> has not re-rendered with the new value yet. That
    // deferral used to be null-checked only when the timeout was *scheduled*,
    // so a submit, a chapter switch or a navigation landing inside the same
    // macrotask left the callback dereferencing `textareaRef.current` from a
    // timer — a TypeError from outside any error boundary, after the component
    // was already gone. The pending restore is tracked so it can be cancelled,
    // and the ref is re-checked inside the callback.
    const restoreTimerRef = useRef(null);

    useEffect(() => () => {
        if (restoreTimerRef.current !== null) {
            clearTimeout(restoreTimerRef.current);
            restoreTimerRef.current = null;
        }
    }, []);

    const handleSelectEntity = useCallback((item, startIndex, endIndex) => {
        const textBefore = editorContent.slice(0, startIndex);
        const textAfter = editorContent.slice(endIndex);
        
        // Link format: [@Name](/world-vault?entity=item.id)
        const link = `[@${item.name}](/world-vault?${item._type}=${item.id})`;
        onEditorChange(textBefore + link + textAfter);
        
        // Restore focus
        if (restoreTimerRef.current !== null) clearTimeout(restoreTimerRef.current);
        restoreTimerRef.current = setTimeout(() => {
            restoreTimerRef.current = null;
            const textarea = textareaRef.current;
            if (!textarea) return;
            textarea.focus();
            textarea.selectionStart = textarea.selectionEnd = startIndex + link.length;
        }, 0);
    }, [editorContent, onEditorChange, textareaRef]);

    return (
        <div className="flex-1 overflow-y-auto custom-scrollbar flex justify-center p-6 lg:p-12" data-color-mode="dark">
            {!activeChapterId ? (
                <div className="flex items-center justify-center text-gray-500 h-full">
                    <p className="text-sm">Select or create a chapter to start writing</p>
                </div>
            ) : (
                <div className="w-full max-w-4xl relative h-full flex flex-col">
                    {!isPreviewMode && (
                        <MentionPicker 
                            textareaRef={textareaRef} 
                            editorContent={editorContent} 
                            onSelect={handleSelectEntity} 
                        />
                    )}
                    <div className="flex-1 w-full bg-gray-900/40 rounded-xl overflow-hidden border border-white/10 shadow-xl relative">
                        <MDEditor
                            value={editorContent}
                            onChange={(val) => { onEditorChange(val || ''); }}
                            preview={isPreviewMode ? 'preview' : 'edit'}
                            hideToolbar={isPreviewMode}
                            height="100%"
                            visibleDragbar={false}
                            className="story-md-editor"
                            textareaProps={{
                                ref: textareaRef,
                                disabled: isStreaming,
                                placeholder: "Begin your story here (Markdown supported)..."
                            }}
                        />
                    </div>
                    
                    {!isPreviewMode && (
                        <div className="flex items-center justify-between text-xs text-gray-600 mt-2 px-1">
                            <span>{wordCount?.toLocaleString?.() || 0} words</span>
                            <span>{readingTimeMinutes || 0} min read</span>
                        </div>
                    )}

                    {!isPreviewMode && !!wordCountGoal && (
                        <div className="mt-1 px-1">
                            <div className="flex items-center justify-between text-xs mb-1">
                                <span className={wordCount >= wordCountGoal ? 'text-emerald-400' : 'text-sky-400'}>
                                    Goal: {Math.min(100, Math.round((wordCount / wordCountGoal) * 100))}%
                                </span>
                                <span className="text-gray-600">of {wordCountGoal.toLocaleString()} words</span>
                            </div>
                            <div className="h-1 rounded-full bg-gray-800 overflow-hidden">
                                <div
                                    className={`h-full rounded-full transition-all duration-500 ${wordCount >= wordCountGoal ? 'bg-emerald-500' : 'bg-sky-500'}`}
                                    style={{ width: `${Math.min(100, (wordCount / wordCountGoal) * 100)}%` }}
                                />
                            </div>
                        </div>
                    )}
                    
                    {isStreaming && (
                        <div className="flex items-center gap-2 text-indigo-400 font-serif mt-4 story-stream-pulse">
                            <Sparkles size={16} />
                            <span>The AI is weaving the next thread...</span>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
});
