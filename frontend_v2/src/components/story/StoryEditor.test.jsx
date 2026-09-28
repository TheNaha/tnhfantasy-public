import { render, screen } from '@testing-library/react';
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
