import React, { useCallback } from 'react';
import { Sparkles } from 'lucide-react';
import MDEditor from '@uiw/react-md-editor';
import MentionPicker from './MentionPicker';

export default React.memo(function StoryEditor({ isPreviewMode, editorContent, onEditorChange, textareaRef, isStreaming, activeChapterId, wordCount, readingTimeMinutes }) {
    const handleSelectEntity = useCallback((item, startIndex, endIndex) => {
        const textBefore = editorContent.slice(0, startIndex);
        const textAfter = editorContent.slice(endIndex);
        
        // Link format: [@Name](/world-vault?entity=item.id)
        const link = `[@${item.name}](/world-vault?${item._type}=${item.id})`;
        onEditorChange(textBefore + link + textAfter);
        
        // Restore focus
        if (textareaRef.current) {
            setTimeout(() => {
                textareaRef.current.focus();
                textareaRef.current.selectionStart = textareaRef.current.selectionEnd = startIndex + link.length;
            }, 0);
        }
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
                        <div className="flex items-center justify-between text-[10px] text-gray-600 mt-2 px-1">
                            <span>{wordCount?.toLocaleString?.() || 0} words</span>
                            <span>{readingTimeMinutes || 0} min read</span>
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
