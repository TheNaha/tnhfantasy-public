import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
    UPLOAD_LIMITS,
    assertUploadAllowed,
    formatBytes,
    isImageFile,
    uploadWithProgress,
} from './upload';
import { ApiError } from './client';
import { filesApi } from './files';
import api from './client';

const MB = 1024 * 1024;

function makeFile(name, { size = 10, type = 'image/png' } = {}) {
    return { name, size, type };
}

describe('upload helpers', () => {
    beforeEach(() => {
        vi.stubGlobal('fetch', vi.fn());
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    describe('formatBytes', () => {
        it('formats byte counts', () => {
            expect(formatBytes(512)).toBe('512 B');
            expect(formatBytes(2048)).toBe('2.0 KB');
            expect(formatBytes(5 * MB)).toBe('5.0 MB');
        });
    });

    describe('isImageFile', () => {
        it('trusts the mime type', () => {
            expect(isImageFile(makeFile('holiday', { type: 'image/jpeg' }))).toBe(true);
        });

        it('falls back to the extension when the type is empty', () => {
            expect(isImageFile({ name: 'holiday.JPEG', size: 1, type: '' })).toBe(true);
        });

        it('rejects non-images', () => {
            expect(isImageFile({ name: 'payload.exe', size: 1, type: 'application/x-msdownload' })).toBe(false);
        });
    });

    describe('assertUploadAllowed', () => {
        it('accepts a normal image', () => {
            expect(assertUploadAllowed(makeFile('a.png'), 'input')).toBe(true);
        });

        it('rejects a missing file', () => {
            expect(() => assertUploadAllowed(null, 'input')).toThrow(ApiError);
        });

        it('rejects an empty file with a clear message', () => {
            expect(() => assertUploadAllowed(makeFile('a.png', { size: 0 }), 'input'))
                .toThrow(/empty/i);
        });

        it('rejects a non-image for image-only endpoints', () => {
            expect(() => assertUploadAllowed(makeFile('payload.exe', { type: '' }), 'input'))
                .toThrow(/image file/i);
        });

        it('rejects an oversized file before the round trip', () => {
            const big = makeFile('a.png', { size: UPLOAD_LIMITS.input.maxBytes + 1 });
            let error;
            try {
                assertUploadAllowed(big, 'input');
            } catch (err) {
                error = err;
            }
            expect(error).toBeInstanceOf(ApiError);
            expect(error.data.code).toBe('UPLOAD_TOO_LARGE');
            expect(error.data.max_bytes).toBe(UPLOAD_LIMITS.input.maxBytes);
            expect(error.message).toMatch(/too large/i);
            expect(fetch).not.toHaveBeenCalled();
        });

        it('allows non-images on the generic file endpoint', () => {
            expect(assertUploadAllowed(makeFile('model.safetensors', { type: '' }), 'file')).toBe(true);
        });
    });
});

describe('uploadWithProgress', () => {
    let xhr;

    function stubXhr() {
        xhr = {
            upload: {},
            open: vi.fn(),
            setRequestHeader: vi.fn(),
            send: vi.fn(),
            abort: vi.fn(() => xhr.onabort && xhr.onabort()),
            status: 200,
            responseText: '{"status":"success"}',
        };
        // A function (not an arrow) so `new XMLHttpRequest()` is valid.
        function FakeXhr() {
            return xhr;
        }
        vi.stubGlobal('XMLHttpRequest', vi.fn(FakeXhr));
        return xhr;
    }

    beforeEach(() => {
        stubXhr();
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('resolves with the parsed body and reports progress', async () => {
        const progress = [];
        const pending = uploadWithProgress('/api/upload', new FormData(), {
            onProgress: (evt) => progress.push(evt),
        });

        xhr.upload.onprogress({ lengthComputable: true, loaded: 5, total: 10 });
        xhr.onload();

        await expect(pending).resolves.toEqual({ status: 'success' });
        expect(progress).toEqual([{ loaded: 5, total: 10, ratio: 0.5 }]);
        expect(xhr.open).toHaveBeenCalledWith('POST', '/api/upload', true);
    });

    it('rejects with the server message and code', async () => {
        const pending = uploadWithProgress('/api/upload', new FormData());
        xhr.status = 400;
        xhr.responseText = JSON.stringify({ error: 'File size exceeds the 50.0 MB limit.', code: 'UPLOAD_TOO_LARGE' });
        xhr.onload();

        await expect(pending).rejects.toMatchObject({
            status: 400,
            message: 'File size exceeds the 50.0 MB limit. (UPLOAD_TOO_LARGE)',
        });
    });

    it('cancels through an AbortSignal', async () => {
        const controller = new AbortController();
        const pending = uploadWithProgress('/api/upload', new FormData(), { signal: controller.signal });
        controller.abort();
        await expect(pending).rejects.toMatchObject({ message: 'Upload cancelled' });
        expect(xhr.abort).toHaveBeenCalled();
    });

    it('rejects immediately for an already-aborted signal', async () => {
        const controller = new AbortController();
        controller.abort();
        await expect(
            uploadWithProgress('/api/upload', new FormData(), { signal: controller.signal })
        ).rejects.toMatchObject({ message: 'Upload cancelled' });
        expect(xhr.send).not.toHaveBeenCalled();
    });
});

describe('filesApi upload wiring', () => {
    beforeEach(() => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            headers: new Headers({ 'content-type': 'application/json' }),
            json: async () => ({ status: 'success', filename: 'a.png' }),
        }));
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('passes the abort signal through the fetch path', async () => {
        const controller = new AbortController();
        await filesApi.uploadInput(makeFile('a.png'), null, { signal: controller.signal });

        const [, config] = fetch.mock.calls[0];
        expect(config.signal).toBe(controller.signal);
        expect(config.method).toBe('POST');
    });

    it('does not set a JSON content type for FormData', async () => {
        await filesApi.uploadInput(makeFile('a.png'));
        const [, config] = fetch.mock.calls[0];
        expect(config.headers['Content-Type']).toBeUndefined();
    });

    it('rejects oversized input images without calling the API', async () => {
        await expect(
            filesApi.uploadInput(makeFile('huge.png', { size: UPLOAD_LIMITS.input.maxBytes + 1 }))
        ).rejects.toThrow(/too large/i);
        expect(fetch).not.toHaveBeenCalled();
    });

    it('surfaces the backend error message', async () => {
        fetch.mockResolvedValueOnce({
            ok: false,
            status: 400,
            headers: new Headers({ 'content-type': 'application/json' }),
            json: async () => ({ error: 'Uploaded image is not a readable image', code: 'INVALID_IMAGE' }),
        });

        await expect(filesApi.uploadInput(makeFile('fake.png'))).rejects.toThrow(/not a readable image/);
    });

    it('rejects an oversized mask payload', async () => {
        const huge = 'A'.repeat(Math.ceil(UPLOAD_LIMITS.input.maxBytes * 1.5));
        await expect(filesApi.uploadMask(huge, 'a.png')).rejects.toThrow(/too large/i);
        expect(fetch).not.toHaveBeenCalled();
    });
});

describe('filesApi.batchDownload', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    function zipResponse({ missingCount, missingFiles } = {}) {
        const headers = new Headers({ 'content-type': 'application/zip' });
        if (missingCount !== undefined) headers.set('x-missing-count', String(missingCount));
        if (missingFiles !== undefined) headers.set('x-missing-files', missingFiles);
        return {
            ok: true,
            status: 200,
            headers,
            blob: async () => new Blob(['zip'], { type: 'application/zip' }),
        };
    }

    it('returns the archive and reports skipped files', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
            zipResponse({ missingCount: 2, missingFiles: 'a.png,b.png' })
        ));

        const result = await filesApi.batchDownload(['a.png', 'b.png', 'c.png']);
        expect(result.blob).toBeInstanceOf(Blob);
        expect(result.missingCount).toBe(2);
        expect(result.missing).toEqual(['a.png', 'b.png']);
    });

    it('rejects when the server returns an error payload instead of a zip', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: false,
            status: 400,
            headers: new Headers({ 'content-type': 'application/json' }),
            json: async () => ({ error: 'None of the 2 requested files exist', code: 'EXPORT_NO_MATCHING_FILES' }),
        }));

        await expect(filesApi.batchDownload(['ghost.png'])).rejects.toMatchObject({
            message: 'None of the 2 requested files exist (EXPORT_NO_MATCHING_FILES)',
        });
    });

    it('rejects a non-archive body instead of saving it as a zip', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            headers: new Headers({ 'content-type': 'text/plain' }),
            text: async () => 'not a zip',
        }));

        await expect(filesApi.batchDownload(['a.png'])).rejects.toThrow(/Download failed/);
    });

    it('rejects an unexpected (non-response) body', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            headers: new Headers({ 'content-type': 'application/json' }),
            json: async () => ({ unexpected: true }),
        }));

        await expect(filesApi.batchDownload(['a.png'])).rejects.toThrow(/unexpected response/);
    });

    it('refuses an empty or oversized selection before the request', async () => {
        vi.stubGlobal('fetch', vi.fn());
        await expect(filesApi.batchDownload([])).rejects.toThrow(/at least one file/i);
        await expect(
            filesApi.batchDownload(new Array(UPLOAD_LIMITS.export.maxFiles + 1).fill('a.png'))
        ).rejects.toThrow(/too many files/i);
        expect(fetch).not.toHaveBeenCalled();
    });

    it('forwards an abort signal', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(zipResponse()));
        const controller = new AbortController();
        await filesApi.batchDownload(['a.png'], { signal: controller.signal });
        expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
    });
});

describe('filesApi keeps the api client mockable', () => {
    it('exports the default client', () => {
        expect(typeof api.post).toBe('function');
    });
});
