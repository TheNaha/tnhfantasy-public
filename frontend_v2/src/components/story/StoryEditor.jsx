import React from 'react';
import { Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default React.memo(function StoryEditor({ isPreviewMode, editorContent, onEditorChange, textareaRef, isStreaming, activeChapterId }) {
    return (
        <div className="flex-1 overflow-y-auto custom-scrollbar flex justify-center p-6 lg:p-12">
            {!activeChapterId ? (
                <div className="flex items-center justify-center text-gray-500">
                    <p className="text-sm">Select or create a chapter to start writing</p>
                </div>
            ) : (
                <div className="w-full max-w-3xl relative h-full min-h-[300px]">
                    {isPreviewMode ? (
                        <div className="w-full text-gray-300 text-lg md:text-xl leading-relaxed font-serif prose prose-invert max-w-none">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                {editorContent || '*No content yet.*'}
                            </ReactMarkdown>
                        </div>
                    ) : (
                        <textarea
                            ref={textareaRef}
                            value={editorContent}
                            onChange={(e) => { onEditorChange(e.target.value); }}
                            className="story-editor-input w-full h-full bg-transparent text-gray-300 text-lg md:text-xl leading-relaxed font-serif focus:outline-none resize-none min-h-[300px]"
                            placeholder="Begin your story here (Markdown supported)..."
                            disabled={isStreaming}
                        />
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
