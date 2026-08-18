import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

const DEFAULT_BRANDING = {
    appName: 'TNH-Comfy',
    logoUrl: '/logo.png',
    faviconUrl: '/favicon.ico',
};

export function useBranding() {
    return useQuery({
        queryKey: ['branding'],
        queryFn: async () => {
            const branding = await api.get('/api/settings/branding');
            return {
                appName: branding?.appName || DEFAULT_BRANDING.appName,
                logoUrl: branding?.logoUrl || DEFAULT_BRANDING.logoUrl,
                faviconUrl: branding?.faviconUrl || DEFAULT_BRANDING.faviconUrl,
            };
        },
        staleTime: 5 * 60 * 1000,
        refetchInterval: 30000,
    });
}

export function useSaveBranding() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (branding) => {
            const payload = {
                appName: branding?.appName || DEFAULT_BRANDING.appName,
                logoUrl: branding?.logoUrl || DEFAULT_BRANDING.logoUrl,
                faviconUrl: branding?.faviconUrl || DEFAULT_BRANDING.faviconUrl,
            };
            await api.post('/api/settings/branding', payload);
            return payload;
        },
        onSuccess: (data) => {
            queryClient.setQueryData(['branding'], data);
        },
    });
}
