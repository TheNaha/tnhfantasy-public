import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// clipboard.js uses DOM APIs - set them up before importing
describe('copyToClipboard', () => {
    let copyToClipboard;

    beforeEach(async () => {
        // Re-import the module fresh for each test
        vi.resetModules();
        const mod = await import('../utils/clipboard.js');
        copyToClipboard = mod.copyToClipboard;
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    describe('when navigator.clipboard is available', () => {
        it('uses clipboard API and returns true on success', async () => {
            const writeText = vi.fn().mockResolvedValue(undefined);
            Object.defineProperty(navigator, 'clipboard', {
                value: { writeText },
                configurable: true,
                writable: true,
            });

            const result = await copyToClipboard('hello world');
            expect(writeText).toHaveBeenCalledWith('hello world');
            expect(result).toBe(true);
        });

        it('falls back to legacy when clipboard API throws', async () => {
            const writeText = vi.fn().mockRejectedValue(new Error('Permission denied'));
            Object.defineProperty(navigator, 'clipboard', {
                value: { writeText },
                configurable: true,
                writable: true,
            });

            // Mock document.execCommand for fallback
            const execCommand = vi.fn().mockReturnValue(true);
            document.execCommand = execCommand;

            const result = await copyToClipboard('test text');
            // Should fall back to execCommand
            expect(execCommand).toHaveBeenCalledWith('copy');
            expect(result).toBe(true);
        });
    });

    describe('when navigator.clipboard is NOT available', () => {
        beforeEach(() => {
            Object.defineProperty(navigator, 'clipboard', {
                value: undefined,
                configurable: true,
                writable: true,
            });
        });

        it('uses textarea fallback and returns true on success', async () => {
            const execCommand = vi.fn().mockReturnValue(true);
            document.execCommand = execCommand;

            const result = await copyToClipboard('fallback text');
            expect(execCommand).toHaveBeenCalledWith('copy');
            expect(result).toBe(true);
        });

        it('returns false when execCommand also fails', async () => {
            document.execCommand = vi.fn().mockImplementation(() => {
                throw new Error('not supported');
            });

            const result = await copyToClipboard('error text');
            expect(result).toBe(false);
        });

        it('cleans up DOM textarea element after copy', async () => {
            document.execCommand = vi.fn().mockReturnValue(true);
            const initialCount = document.body.children.length;

            await copyToClipboard('cleanup test');

            // Textarea should have been removed
            expect(document.body.children.length).toBe(initialCount);
        });
    });
});
