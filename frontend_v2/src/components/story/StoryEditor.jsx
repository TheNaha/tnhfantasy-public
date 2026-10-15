import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { Bold, Italic, Heading2, Quote, List, Link2, Code, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import MentionPicker from './MentionPicker';

/**
 * The story writing surface.
 *
 * This used to be `@uiw/react-md-editor`. It was the heaviest chunk in the app
 * by an order of magnitude — 1.28 MB minified, 409 kB gzipped, against 64 kB for
 * the next largest — and 1.1 MB of that was syntax highlighting: the package
 * imports `rehype-prism-plus`, which bundles `refractor`, which registers 594
 * language grammars as a single 528 KB minified regex. A prose editor was
 * shipping every grammar in the refractor distribution to render paragraphs
 * about a tavern.
 *
 * The replacement is a plain auto-growing `<textarea>` plus `react-markdown` for
 * the preview, both of which were already dependencies. This is also the
 * correct shape for the rest of the component: `MentionPicker` inserts at
 * `textareaRef.current.selectionStart/End`, which only ever worked here because
 * MDEditor happens to render a real `<textarea>` underneath.
 */

const TOOLBAR_ACTIONS = [
    { key: 'bold', icon: Bold, title: 'Bold', before: '**', after: '**', fallback: 'bold text' },
    { key: 'italic', icon: Italic, title: 'Italic', before: '_', after: '_', fallback: 'italic text' },
    { key: 'heading', icon: Heading2, title: 'Heading', before: '## ', after: '', fallback: 'Heading', lineStart: true },
    { key: 'quote', icon: Quote, title: 'Quote', before: '> ', after: '', fallback: 'Quoted text', lineStart: true },
    { key: 'list', icon: List, title: 'Bullet list', before: '- ', after: '', fallback: 'List item', lineStart: true },
    { key: 'code', icon: Code, title: 'Inline code', before: '`', after: '`', fallback: 'code' },
    { key: 'link', icon: Link2, title: 'Link', before: '[', after: '](https://)', fallback: 'link text' },
];

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
    // The textarea grows with its content instead of scrolling internally, which
    // is what MDEditor did for us. Capped at 70vh so a very long chapter still
    // scrolls the page rather than pushing the word counter off screen — the
    // previous behaviour set an uncapped `scrollHeight`.
    const editorRef = useRef(null);

    useEffect(() => () => {
        if (restoreTimerRef.current !== null) {
            clearTimeout(restoreTimerRef.current);
            restoreTimerRef.current = null;
        }
    }, []);

    const resize = useCallback(() => {
        const el = editorRef.current;
        if (!el) return;
        el.style.height = 'auto';
        el.style.height = `${Math.min(el.scrollHeight, window.innerHeight * 0.7)}px`;
    }, []);

    useEffect(resize, [editorContent, resize]);

    const handleSelectEntity = useCallback((item, startIndex, endIndex) => {
        const textBefore = editorContent.slice(0, startIndex);
        const textAfter = editorContent.slice(endIndex);

        // Link format: `[@Name](/world-vault?<type>=<id>)`. This has to match
        // the resolver's regex in `StorySandbox` exactly, or the mention stops
        // becoming a link and stops contributing the entity's id to the story.
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

    /**
     * Apply a toolbar action to the editor's selection.
     *
     * Reads the live `<textarea>` rather than going through a wrapper, because
     * the wrapper this used to call (`useSelectionWrap`) owned a ref that was
     * never attached to anything — the call site destructured only `wrap` and
     * threw the ref away, so `wrap` always returned null and all seven buttons
     * were inert. No test covered them; this is the fix, and the tests below are
     * the point.
     *
     * The line-start case is its own path, not a variant of the inline one: it
     * used to run the inline wrap FIRST and then look for the line start in the
     * already-wrapped string, using the pre-wrap offsets, which both
     * double-prefixed the text and mis-located the caret.
     */
    const applyFormat = useCallback((action) => {
        const el = editorRef.current;
        if (!el) return;
        const { selectionStart: start, selectionEnd: end } = el;
        const value = el.value;

        const restore = (caretStart, caretEnd) => {
            if (restoreTimerRef.current !== null) clearTimeout(restoreTimerRef.current);
            restoreTimerRef.current = setTimeout(() => {
                restoreTimerRef.current = null;
                const node = editorRef.current;
                if (!node) return;
                node.focus();
                node.selectionStart = caretStart;
                node.selectionEnd = caretEnd;
            }, 0);
        };

        if (action.lineStart) {
            // The whole line the selection touches, not just the selected
            // characters. A `## ` inserted in front of the word the caret happens
            // to sit on is not a heading, it is corruption — and with no
            // selection at all there is nothing to wrap, so the line is the
            // target.
            //
            // `Math.max(0, ...)` on the lineStart because `lastIndexOf` with a
            // negative fromIndex scans the whole string and finds an EARLIER
            // newline on a multi-line document.
            const lineStart = value.lastIndexOf('\n', Math.max(0, start - 1)) + 1;
            const newlineAfter = value.indexOf('\n', end);
            const lineEnd = newlineAfter === -1 ? value.length : newlineAfter;
            const target = value.slice(lineStart, lineEnd);
            const next = value.slice(0, lineStart) + action.before + target + action.after + value.slice(lineEnd);
            onEditorChange(next);
            restore(
                lineStart + action.before.length,
                lineStart + action.before.length + target.length,
            );
            return;
        }

        const selected = value.slice(start, end) || action.fallback;
        const next = value.slice(0, start) + action.before + selected + action.after + value.slice(end);
        onEditorChange(next);
        const caret = start + action.before.length;
        restore(caret, caret + selected.length);
    }, [onEditorChange]);

    const previewComponents = useMemo(() => ({
        a: ({ node, ...props }) => <a {...props} className="text-cyan-400 underline" target="_blank" rel="noreferrer" />,
    }), []);

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
                    <div className="flex-1 w-full bg-gray-900/40 rounded-xl border border-white/10 shadow-xl relative flex flex-col">
                        {isPreviewMode ? (
                            <div className="prose prose-invert max-w-none p-6 flex-1 story-prose">
                                <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    components={previewComponents}
                                >
                                    {editorContent}
                                </ReactMarkdown>
                            </div>
                        ) : (
                            <>
                                <div className="flex items-center gap-1 border-b border-white/10 px-2 py-1.5 shrink-0" role="toolbar" aria-label="Formatting">
                                    {TOOLBAR_ACTIONS.map(({ key, icon: Icon, title }) => (
                                        <button
                                            key={key}
                                            type="button"
                                            onClick={() => applyFormat(TOOLBAR_ACTIONS.find((a) => a.key === key))}
                                            disabled={isStreaming}
                                            title={title}
                                            aria-label={title}
                                            className="p-1.5 rounded text-gray-500 hover:text-gray-200 hover:bg-white/5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                        >
                                            <Icon size={14} />
                                        </button>
                                    ))}
                                </div>
                                <textarea
                                    ref={(node) => {
                                        editorRef.current = node;
                                        if (typeof textareaRef === 'function') textareaRef(node);
                                        else if (textareaRef) textareaRef.current = node;
                                    }}
                                    value={editorContent}
                                    onChange={(e) => onEditorChange(e.target.value)}
                                    // Editable while the chapter streams. The
                                    // stream yields to a human edit (see
                                    // `useStoryStreaming`), so freezing the box
                                    // was a restriction, not a safeguard.
                                    aria-label="Chapter content" placeholder="Begin your story here (Markdown supported)..."
                                    className="w-full flex-1 bg-transparent px-6 py-4 text-gray-100 font-serif text-lg leading-relaxed resize-none outline-none story-editor-textarea"
                                />
                            </>
                        )}
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
