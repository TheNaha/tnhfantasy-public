import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import api, { ApiError } from './client';

describe('ApiClient', () => {
    beforeEach(() => {
        vi.stubGlobal('fetch', vi.fn());
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    describe('ApiError', () => {
        it('should create an ApiError instance', () => {
            const error = new ApiError('Test error', 400, { detail: 'error details' });
            expect(error).toBeInstanceOf(Error);
            expect(error).toBeInstanceOf(ApiError);
            expect(error.message).toBe('Test error');
            expect(error.status).toBe(400);
            expect(error.data).toEqual({ detail: 'error details' });
        });
    });

    describe('request', () => {
        it('should handle successful JSON responses', async () => {
            const mockData = { success: true };
            fetch.mockResolvedValue({
                ok: true,
                headers: new Headers({ 'content-type': 'application/json' }),
                json: async () => mockData,
            });

            const result = await api.get('/test');
            expect(result).toEqual(mockData);
            expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/test'), expect.objectContaining({
                method: 'GET',
                headers: expect.objectContaining({
                    'Content-Type': 'application/json'
                })
            }));
        });

        it('should handle successful non-JSON responses', async () => {
            const mockResponse = {
                ok: true,
                headers: new Headers({ 'content-type': 'image/png' }),
            };
            fetch.mockResolvedValue(mockResponse);

            const result = await api.get('/image');
            expect(result).toBe(mockResponse);
        });

        it('should handle non-JSON error responses (the specific gap)', async () => {
            fetch.mockResolvedValue({
                ok: false,
                status: 500,
                headers: new Headers({ 'content-type': 'text/plain' }),
            });

            await expect(api.get('/error')).rejects.toThrow(ApiError);
            try {
                await api.get('/error');
            } catch (error) {
                expect(error.message).toBe('Request failed');
                expect(error.status).toBe(500);
            }
        });

        it('should handle JSON error responses with data.error', async () => {
            const errorData = { error: 'Specific error message' };
            fetch.mockResolvedValue({
                ok: false,
                status: 400,
                headers: new Headers({ 'content-type': 'application/json' }),
                json: async () => errorData,
            });

            await expect(api.get('/error')).rejects.toThrow('Specific error message');
            try {
                await api.get('/error');
            } catch (error) {
                expect(error.status).toBe(400);
                expect(error.data).toEqual(errorData);
            }
        });

        it('should handle JSON error responses with data.detail', async () => {
            const errorData = { detail: 'Detail error message' };
            fetch.mockResolvedValue({
                ok: false,
                status: 400,
                headers: new Headers({ 'content-type': 'application/json' }),
                json: async () => errorData,
            });

            await expect(api.get('/error')).rejects.toThrow('Detail error message');
        });

        it('should handle network failures', async () => {
            fetch.mockRejectedValue(new Error('Network failure'));

            await expect(api.get('/test')).rejects.toThrow(ApiError);
            try {
                await api.get('/test');
            } catch (error) {
                expect(error.message).toBe('Network failure');
                expect(error.status).toBe(0);
            }
        });

        it('should handle FormData correctly', async () => {
            const formData = new FormData();

            fetch.mockResolvedValue({
                ok: true,
                headers: new Headers({ 'content-type': 'application/json' }),
                json: async () => ({ success: true }),
            });

            await api.post('/upload', formData);

            const call = fetch.mock.calls[0];
            expect(call[1].headers['Content-Type']).toBeUndefined();
            expect(call[1].body).toBe(formData);
        });
    });

    describe('helper methods', () => {
        beforeEach(() => {
            fetch.mockResolvedValue({
                ok: true,
                headers: new Headers({ 'content-type': 'application/json' }),
                json: async () => ({ success: true }),
            });
        });

        it('should perform GET request', async () => {
            await api.get('/test');
            expect(fetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ method: 'GET' }));
        });

        it('should perform POST request', async () => {
            await api.post('/test', { data: 'test' });
            expect(fetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({
                method: 'POST',
                body: JSON.stringify({ data: 'test' })
            }));
        });

        it('should perform PUT request', async () => {
            await api.put('/test', { data: 'test' });
            expect(fetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({
                method: 'PUT',
                body: JSON.stringify({ data: 'test' })
            }));
        });

        it('should perform PATCH request', async () => {
            await api.patch('/test', { data: 'test' });
            expect(fetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({
                method: 'PATCH',
                body: JSON.stringify({ data: 'test' })
            }));
        });

        it('should perform DELETE request', async () => {
            await api.delete('/test');
            expect(fetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ method: 'DELETE' }));
        });
    });
});
