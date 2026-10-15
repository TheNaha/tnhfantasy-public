import { fireEvent, render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import React from 'react';

// `@uiw/react-md-editor` is gone: it pulled `rehype-prism-plus` -> `refractor`,
// which registers 594 language grammars (1.1 MB minified) into the app's
// heaviest chunk, to render a prose editor's paragraphs. Nothing to mock.
vi.mock('./MentionPicker', () => ({ default: () => <div /> }));

import StoryEditor from './StoryEditor';

const baseProps = {
    isPreviewMode: false,
    editorContent: 'Once upon a time',
    onEditorChange: vi.fn(),
    textareaRef: React.createRef(),
    isStreaming: false,
    activeChapterId: 'ch-1',
    wordCount: 250,
    readingTimeMinutes: 2,
};

describe('StoryEditor', () => {
    it('shows word count and reading time', () => {
        render(<StoryEditor {...baseProps} />);
        expect(screen.getByText(/250 words/)).toBeInTheDocument();
        expect(screen.getByText('2 min read')).toBeInTheDocument();
        expect(screen.queryByText(/Goal:/)).not.toBeInTheDocument();
    });

    it('renders goal progress when a goal is set', () => {
        render(<StoryEditor {...baseProps} wordCountGoal={1000} />);
        expect(screen.getByText('of 1,000 words')).toBeInTheDocument();
        expect(screen.getByText('Goal: 25%')).toBeInTheDocument();
    });

    it('caps displayed progress at 100% and marks goal complete', () => {
        render(<StoryEditor {...baseProps} wordCount={1200} wordCountGoal={1000} />);
        expect(screen.getByText('Goal: 100%')).toBeInTheDocument();
    });

    it('hides goal bar in preview mode', () => {
        render(<StoryEditor {...baseProps} wordCountGoal={1000} isPreviewMode={true} />);
        expect(screen.queryByText(/Goal:/)).not.toBeInTheDocument();
    });
});

describe('StoryEditor formatting toolbar', () => {
    // Until 2026-10-13 every one of these buttons was inert. `useSelectionWrap`
    // created its own ref, the destructuring at the call site discarded it, and
    // `wrap` returned null every time — so the toolbar rendered, looked live, and
    // did nothing. Nothing covered it because the tests cover word count.

    const boldButton = () => screen.getByRole('button', { name: 'Bold' });

    /**
     * Put real text in the REAL textarea.
     *
     * `StoryEditor` is controlled and `onEditorChange` is a mock, so
     * `fireEvent.change` is reverted by React on the next render and the node
     * reads back whatever `editorContent` was. Setting through the native value
     * setter is what leaves the DOM the way a user's own typing does, which is
     * what `applyFormat` reads.
     */
    const typeInto = (node, text, from = 0, to = 0) => {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
        setter.call(node, text);
        node.setSelectionRange(from, to);
    };

    it('wraps the selection in the markers', () => {
        const ref = React.createRef();
        const onEditorChange = vi.fn();
        render(<StoryEditor {...baseProps} textareaRef={ref} onEditorChange={onEditorChange} />);

        const textarea = screen.getByLabelText('Chapter content');
        typeInto(textarea, 'Once upon a time', 5, 10);

        fireEvent.click(boldButton());

        expect(onEditorChange).toHaveBeenCalled();
        const next = onEditorChange.mock.calls.at(-1)[0];
        // selection 5..10 of 'Once upon a time' is 'upon '.
        expect(next).toBe('Once **upon **a time');
    });

    it('inserts the fallback when nothing is selected', () => {
        const onEditorChange = vi.fn();
        render(<StoryEditor {...baseProps} onEditorChange={onEditorChange} />);
        const textarea = screen.getByLabelText('Chapter content');
        typeInto(textarea, baseProps.editorContent, 0, 0);

        fireEvent.click(boldButton());

        const next = onEditorChange.mock.calls.at(-1)[0];
        expect(next).toContain('**bold text**');
    });

    it('inserts a line-start marker at the start of the line, not mid-word', () => {
        const onEditorChange = vi.fn();
        render(<StoryEditor {...baseProps} onEditorChange={onEditorChange} />);
        const textarea = screen.getByLabelText('Chapter content');
        typeInto(textarea, 'first line\nsecond line', 14, 17);

        fireEvent.click(screen.getByRole('button', { name: 'Heading' }));

        const next = onEditorChange.mock.calls.at(-1)[0];
        expect(next).toBe('first line\n## second line');
    });
});
