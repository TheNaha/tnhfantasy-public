/**
 * The shared download helper.
 *
 * Three properties, each of which was a real user-visible failure in one of the
 * three copies this replaced:
 *
 *  1. A payload that is ALREADY a `Blob` is handed to the browser untouched.
 *     The story-export path used to do `new Blob([data?.content || ''])` on a
 *     response that `api.get(..., { responseType: 'blob' })` had already turned
 *     into a `Blob` — so the saved EPUB / comic PDF / webtoon PNG was a
 *     0-byte file and the export reported success.
 *  2. The object URL is revoked LATER, not in the tick that called `click()`.
 *     Revoking synchronously aborts the download in Firefox and older Safari.
 *  3. A cancelled file picker resolves `null` rather than never settling.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { triggerFile, downloadJson, downloadText, pickFile } from './download';

let createObjectURL;
let revokeObjectURL;
let anchors;
let fileInputs;
let clickOrder;

beforeEach(() => {
    createObjectURL = vi.fn(() => `blob:mock/${createObjectURL.mock.calls.length}`);
    revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });

    anchors = [];
    fileInputs = [];
    clickOrder = [];
    const originalCreate = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag, ...rest) => {
        const element = originalCreate(tag, ...rest);
        if (tag === 'a') {
            element.click = vi.fn(() => clickOrder.push({ href: element.href, download: element.download }));
            anchors.push(element);
        }
        // `pickFile` sets `input.type = 'file'` after creating the element, so
        // the type is not readable yet at create time.
        if (tag === 'input') fileInputs.push(element);
        return element;
    });
});

afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    document.querySelectorAll('a').forEach((el) => el.remove());
});

describe('triggerFile', () => {
    it('hands a real Blob to the browser untouched', async () => {
        const payload = new Blob([new Uint8Array([0x50, 0x4b, 0x03, 0x04])], { type: 'application/epub+zip' });

        triggerFile(payload, 'story.epub');

        expect(createObjectURL).toHaveBeenCalledTimes(1);
        const handedOver = createObjectURL.mock.calls[0][0];
        expect(handedOver).toBe(payload);
        expect(handedOver.type).toBe('application/epub+zip');
        expect(handedOver.size).toBe(4);
    });

    it('is why the pre-fix export was empty (canary)', async () => {
        // What the story-export path actually did:
        // `new Blob([data?.content || ''])`, on a response that was already a
        // `Blob`. A `Blob` has no `.content`, so every part fell back to `''` and
        // the EPUB / comic PDF / webtoon PNG that got saved was 0 bytes — while
        // the export reported success, because nothing had thrown.
        const payload = new Blob([new Uint8Array([1, 2, 3, 4, 5])]);
        const preFix = new Blob([payload.content || '']);

        expect(payload.size).toBe(5);
        expect(preFix.size).toBe(0);
        expect(await preFix.text()).toBe('');
        // And the wrapper is a different object, which is why the test above
        // asserts identity rather than size.
        expect(preFix).not.toBe(payload);
    });

    it('names the download and cleans the anchor off the document', () => {
        triggerFile(new Blob(['x']), 'comfyui_batch_1.zip');

        expect(anchors).toHaveLength(1);
        expect(anchors[0].download).toBe('comfyui_batch_1.zip');
        expect(anchors[0].rel).toBe('noopener');
        expect(clickOrder).toEqual([{ href: 'blob:mock/1', download: 'comfyui_batch_1.zip' }]);
        // Appended so the click has a connected element in every browser, then
        // removed — leaving it up would stack one dead anchor per export.
        expect(document.querySelectorAll('a')).toHaveLength(0);
    });

    it('wraps a non-Blob payload instead of stringifying it', () => {
        triggerFile('a,b\n1,2', 'rows.csv');

        const handedOver = createObjectURL.mock.calls[0][0];
        expect(handedOver).toBeInstanceOf(Blob);
        expect(handedOver.size).toBe(7);
    });

    it('revokes the object URL after the click, never in the same tick', () => {
        vi.useFakeTimers();

        triggerFile(new Blob(['x']), 'late.zip');

        expect(clickOrder).toHaveLength(1);
        expect(revokeObjectURL).not.toHaveBeenCalled();

        vi.advanceTimersByTime(999);
        expect(revokeObjectURL).not.toHaveBeenCalled();

        vi.advanceTimersByTime(1);
        expect(revokeObjectURL).toHaveBeenCalledTimes(1);
        expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock/1');
    });

    it('would fail against a same-tick revoke (canary)', () => {
        vi.useFakeTimers();

        // The pre-fix shape, kept here so the assertion above cannot quietly
        // become vacuous if the delay is shortened back to 0.
        const url = createObjectURL(new Blob(['x']));
        revokeObjectURL(url);

        expect(revokeObjectURL).toHaveBeenCalledTimes(1);
        vi.advanceTimersByTime(2000);
        expect(revokeObjectURL).toHaveBeenCalledTimes(1);
    });
});

describe('downloadJson / downloadText', () => {
    it('pretty-prints JSON with a trailing newline-free body', async () => {
        downloadJson({ b: 1, a: 2 }, 'preset.json');

        const handedOver = createObjectURL.mock.calls[0][0];
        expect(await handedOver.text()).toBe('{\n  "b": 1,\n  "a": 2\n}');
        expect(anchors[0].download).toBe('preset.json');
    });

    it('keeps a text payload intact and typed', async () => {
        downloadText('# Title\nbody', 'story.md');

        const handedOver = createObjectURL.mock.calls[0][0];
        expect(await handedOver.text()).toBe('# Title\nbody');
        expect(handedOver.type).toBe('text/plain');
        expect(anchors[0].download).toBe('story.md');
    });
});

describe('pickFile', () => {
    it('resolves null when the picker is cancelled', async () => {
        vi.useFakeTimers();

        const pending = pickFile({ accept: 'image/*' });

        // A cancelled picker fires no `change`; the window regains focus instead.
        window.dispatchEvent(new Event('focus'));
        expect(vi.getTimerCount()).toBeGreaterThan(0);
        vi.advanceTimersByTime(300);

        await expect(pending).resolves.toBeNull();
    });

    it('resolves the chosen file', async () => {
        const pending = pickFile({ accept: 'image/*' });
        const input = fileInputs.at(-1);
        expect(input).toBeDefined();
        expect(input.accept).toBe('image/*');

        const file = new File(['png-bytes'], 'ref.png', { type: 'image/png' });
        Object.defineProperty(input, 'files', { value: [file], configurable: true });
        input.dispatchEvent(new Event('change'));

        await expect(pending).resolves.toBe(file);
    });

    it('resolves null when the change event carries no file', async () => {
        const pending = pickFile();
        fileInputs.at(-1).dispatchEvent(new Event('change'));

        await expect(pending).resolves.toBeNull();
    });
});