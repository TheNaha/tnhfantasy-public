import { render, act } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

let lastToasterProps = null;

vi.mock('react-hot-toast', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        Toaster: (props) => {
            lastToasterProps = props;
            return <div data-testid="mock-toaster" data-position={props.position} />;
        },
    };
});

vi.mock('../api/websocket', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        connect: vi.fn().mockResolvedValue(),
        subscribe: vi.fn().mockResolvedValue(),
        unsubscribe: vi.fn(),
        on: vi.fn(() => () => {}),
        getConnectionStatus: vi.fn(() => true),
    };
});

vi.mock('../hooks/useJobsRealtime', () => ({
    useJobsRealtime: () => {},
    default: () => {},
}));

import App from '../App';

function setViewportWidth(width) {
    Object.defineProperty(window, 'innerWidth', {
        writable: true,
        configurable: true,
        value: width,
    });
}

describe('Toaster positioning', () => {
    beforeEach(() => {
        lastToasterProps = null;
    });

    it('positions Toaster on top-left for mobile viewports (< 768px)', async () => {
        setViewportWidth(500);
        render(<App />);

        expect(lastToasterProps?.position).toBe('top-left');
    });

    it('positions Toaster on top-right for desktop viewports (>= 768px)', async () => {
        setViewportWidth(1024);
        render(<App />);

        expect(lastToasterProps?.position).toBe('top-right');
    });

    it('dynamically adapts position on window resize', async () => {
        setViewportWidth(1024);
        render(<App />);
        expect(lastToasterProps?.position).toBe('top-right');

        act(() => {
            setViewportWidth(480);
            window.dispatchEvent(new Event('resize'));
        });

        expect(lastToasterProps?.position).toBe('top-left');
    });
});
