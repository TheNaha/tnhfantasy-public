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

        it('removes the textarea when execCommand is missing, which is the leak', async () => {
            // `document.execCommand` is `undefined` in jsdom and removed from
            // several browsers. With the `removeChild` after the call rather
            // than in a `finally`, that throw skipped it, so every copy on such
            // an origin left a focusable textarea in the live document.
            delete document.execCommand;

            await copyToClipboard('leak probe');

            expect(document.querySelectorAll('textarea')).toHaveLength(0);
            expect(document.body.textContent).not.toContain('leak probe');
        });

        it('leaves no textarea behind when execCommand itself throws', async () => {
            document.execCommand = vi.fn().mockImplementation(() => {
                throw new Error('not supported');
            });

            await expect(copyToClipboard('throw probe')).resolves.toBe(false);

            expect(document.querySelectorAll('textarea')).toHaveLength(0);
        });

        it('can tell a leaking fallback from a clean one (canary)', async () => {
            // The pre-fix implementation, in isolation. If this stops leaving a
            // textarea behind, the two assertions above have stopped meaning
            // anything.
            const leakyCopy = () => {
                let textArea = null;
                try {
                    textArea = document.createElement('textarea');
                    textArea.value = 'leaky';
                    document.body.appendChild(textArea);
                    textArea.focus();
                    return document.execCommand('copy');
                } catch {
                    return false;
                } finally {
                    /* the missing removeChild */
                }
            };

            delete document.execCommand;
            leakyCopy();
            expect(document.querySelectorAll('textarea')).toHaveLength(1);

            document.querySelectorAll('textarea').forEach((el) => el.remove());
        });
    });
});
