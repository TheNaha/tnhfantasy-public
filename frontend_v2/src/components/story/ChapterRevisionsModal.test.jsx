import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ChapterRevisionsModal from './ChapterRevisionsModal';

const REVISIONS = [
    { id: 'rev-1', source: 'pre_retry', word_count: 42, created_at: '2026-08-26T10:00:00Z', preview: 'The newest snapshot text' },
    { id: 'rev-2', source: 'manual', word_count: 12, created_at: '2026-08-25T09:00:00Z', preview: 'An older manual save' },
];

describe('ChapterRevisionsModal', () => {
    it('renders nothing when closed', () => {
        render(<ChapterRevisionsModal isOpen={false} revisions={REVISIONS} onRestore={vi.fn()} onClose={vi.fn()} />);
        expect(screen.queryByTestId('revisions-modal')).toBeNull();
    });

    it('lists revisions with source labels and word counts', () => {
        render(<ChapterRevisionsModal isOpen chapterTitle="Chapter 1" revisions={REVISIONS} onRestore={vi.fn()} onClose={vi.fn()} />);
        expect(screen.getByTestId('revisions-modal')).toBeInTheDocument();
        expect(screen.getAllByTestId('revision-row')).toHaveLength(2);
        expect(screen.getByText('Before retry')).toBeInTheDocument();
        expect(screen.getByText('Manual save')).toBeInTheDocument();
        expect(screen.getByText(/42 words/)).toBeInTheDocument();
        expect(screen.getByText('The newest snapshot text')).toBeInTheDocument();
    });

    it('shows the empty state when there are no snapshots', () => {
        render(<ChapterRevisionsModal isOpen chapterTitle="Chapter 1" revisions={[]} isLoading={false} onRestore={vi.fn()} onClose={vi.fn()} />);
        expect(screen.getByText(/No snapshots yet/i)).toBeInTheDocument();
    });

    it('calls onRestore with the chosen revision', () => {
        const onRestore = vi.fn();
        render(<ChapterRevisionsModal isOpen chapterTitle="Chapter 1" revisions={REVISIONS} isRestoring={false} onRestore={onRestore} onClose={vi.fn()} />);
        const restoreButtons = screen.getAllByTitle('Restore this revision');
        fireEvent.click(restoreButtons[1]);
        expect(onRestore).toHaveBeenCalledWith(REVISIONS[1]);
    });

    it('calls onSnapshot from the snapshot button', () => {
        const onSnapshot = vi.fn();
        render(<ChapterRevisionsModal isOpen chapterTitle="Chapter 1" revisions={[]} onSnapshot={onSnapshot} onRestore={vi.fn()} onClose={vi.fn()} />);
        fireEvent.click(screen.getByTitle("Save a snapshot of the chapter's current prose"));
        expect(onSnapshot).toHaveBeenCalledTimes(1);
    });
});
