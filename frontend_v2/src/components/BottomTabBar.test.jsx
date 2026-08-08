import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MessageSquare } from 'lucide-react';
import BottomTabBar from './BottomTabBar';

describe('BottomTabBar', () => {
    const tabs = [
        { id: 'chat', label: 'Chat', icon: MessageSquare },
        { id: 'story', label: 'Story' },
        { id: 'context', label: 'Context', badge: 3 },
    ];

    it('renders one tab per entry with its label', () => {
        render(<BottomTabBar tabs={tabs} value="chat" onChange={() => {}} />);
        expect(screen.getByText('Chat')).toBeInTheDocument();
        expect(screen.getByText('Story')).toBeInTheDocument();
        expect(screen.getByText('Context')).toBeInTheDocument();
    });

    it('marks the active tab with aria-pressed and calls onChange on click', () => {
        const onChange = vi.fn();
        render(<BottomTabBar tabs={tabs} value="chat" onChange={onChange} />);

        const storyBtn = screen.getByText('Story').closest('button');
        expect(storyBtn).not.toBeNull();
        // 'chat' is active, so the Story tab is not.
        expect(storyBtn).toHaveAttribute('aria-pressed', 'false');

        fireEvent.click(storyBtn);
        expect(onChange).toHaveBeenCalledWith('story');
    });

    it('renders a badge for numeric counts', () => {
        render(<BottomTabBar tabs={tabs} value="context" onChange={() => {}} />);
        expect(screen.getByText('3')).toBeInTheDocument();
    });

    it('renders nothing when there are no tabs', () => {
        const { container } = render(<BottomTabBar tabs={[]} value={null} onChange={() => {}} />);
        expect(container.firstChild).toBeNull();
    });

    it('renders as an inline strip (no fixed spacer) when inline is set', () => {
        const { container } = render(
            <BottomTabBar tabs={tabs} value="chat" onChange={() => {}} inline />
        );
        // Inline mode renders a single <nav> strip (no fixed spacer sibling).
        const navs = container.querySelectorAll('nav');
        expect(navs).toHaveLength(1);
        expect(navs[0].className).toMatch(/flex items-center justify-around/);
        expect(navs[0].className).toMatch(/lg:hidden/);
        // The fixed-bottom spacer must not be present in inline mode.
        expect(navs[0].className).not.toMatch(/fixed bottom-0/);
    });

    it('applies a per-tab active color class', () => {
        render(
            <BottomTabBar
                tabs={[
                    { id: 'chat', label: 'Chat', icon: MessageSquare, color: 'text-purple-400' },
                ]}
                value="chat"
                onChange={() => {}}
            />
        );
        const btn = screen.getByText('Chat').closest('button');
        expect(btn.className).toMatch(/text-purple-400/);
    });
});
