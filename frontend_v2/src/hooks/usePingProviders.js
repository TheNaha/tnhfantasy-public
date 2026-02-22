import { useEffect } from 'react';
import { api } from '../api';

/**
 * Hook to ping the backend to wake up provider containers from cold start.
 * Use this in pages where the user is likely to generate an image soon.
 */
export function usePingProviders() {
    useEffect(() => {
        api.post('/api/providers/wake').catch(err => {
            console.warn('Failed to send wake signal to providers:', err);
        });
    }, []);
}
