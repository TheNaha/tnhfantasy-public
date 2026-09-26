import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { settingsApi } from '../api/settingsApi';

const DEFAULT_BRANDING = {
    appName: 'TNH-Comfy',
    logoUrl: '/logo.png',
    faviconUrl: '/favicon.ico',
};

export function useBranding() {
    return useQuery({
        queryKey: ['branding'],
        queryFn: async () => {
            const branding = await settingsApi.getBranding();
            return {
                appName: branding?.appName || DEFAULT_BRANDING.appName,
                logoUrl: branding?.logoUrl || DEFAULT_BRANDING.logoUrl,
                faviconUrl: branding?.faviconUrl || DEFAULT_BRANDING.faviconUrl,
            };
        },
        staleTime: 5 * 60 * 1000,
        // No refetchInterval. Branding only changes when a user saves it, and
        // useSaveBranding already updates the cache optimistically. Polling
        // every 30s from a Layout-mounted hook meant a permanent request per
        // page load for data that is effectively static.
        refetchInterval: false,
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
            await settingsApi.updateBranding(payload);
            return payload;
        },
        onSuccess: (data) => {
            queryClient.setQueryData(['branding'], data);
        },
    });
}
