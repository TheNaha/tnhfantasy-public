import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import {
    ImageSkeleton,
    CardSkeleton,
    GallerySkeleton,
    FeedCardSkeleton,
    ModelCardSkeleton,
    TextSkeleton,
    StatsSkeleton,
    TableSkeleton
} from './Skeleton';

describe('Skeleton Components', () => {
    it('ImageSkeleton renders correctly', () => {
        const { container } = render(<ImageSkeleton className="test-class" aspectRatio="video" />);
        expect(container.firstChild).toHaveClass('test-class');
        expect(container.querySelector('.aspect-video')).toBeInTheDocument();
    });

    it('CardSkeleton renders correctly', () => {
        const { container } = render(<CardSkeleton className="test-class" />);
        expect(container.firstChild).toHaveClass('test-class');
    });

    it('GallerySkeleton renders grid correctly', () => {
        const { container } = render(<GallerySkeleton count={4} mode="grid" />);
        expect(container.firstChild).toHaveClass('grid');
        expect(container.querySelectorAll('.aspect-square').length).toBe(4);
    });

    it('GallerySkeleton renders list correctly', () => {
        const { container } = render(<GallerySkeleton count={3} mode="list" />);
        // container.firstChild is the <div className="space-y-2">
        // Its children are the 3 items
        expect(container.firstChild).toHaveClass('space-y-2');
        expect(container.firstChild.children.length).toBe(3);
    });

    it('FeedCardSkeleton renders correctly', () => {
        const { container } = render(<FeedCardSkeleton />);
        expect(container.firstChild).toHaveClass('rounded-2xl');
    });

    it('ModelCardSkeleton renders correctly', () => {
        const { container } = render(<ModelCardSkeleton />);
        expect(container.firstChild).toHaveClass('rounded-xl');
    });

    it('TextSkeleton renders correct number of lines', () => {
        // SkeletonBase adds a Shimmer element, so expect lines + 1
        const { container } = render(<TextSkeleton lines={5} />);
        expect(container.firstChild.children.length).toBe(5 + 1);
    });

    it('StatsSkeleton renders 4 items', () => {
        const { container } = render(<StatsSkeleton />);
        expect(container.firstChild.children.length).toBe(4);
    });

    it('TableSkeleton renders correct rows and cols', () => {
        // Header + 3 rows + Shimmer = 5
        const { container } = render(<TableSkeleton rows={3} cols={2} />);
        expect(container.firstChild.children.length).toBe(1 + 3 + 1);
    });
});
