import { useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { settingsApi } from '../api/settingsApi';

const DEFAULT_BRANDING = {
    appName: 'TNH-Comfy',
    logoUrl: '/logo.png',
    faviconUrl: '/favicon.ico',
};

/**
 * Push the configured app name into the document title.
 *
 * The Settings field for `appName` is labelled "The name displayed in the browser
 * tab and sidebar", and only the second half was true: `index.html` hardcoded
 * `<title>TNH-Comfy</title>` and nothing anywhere in the app assigned
 * `document.title`. Renaming the app in Settings updated the sidebar and left
 * the tab alone — a setting that silently does half of what it says.
 *
 * The favicon is NOT applied here. That is a different file (a static asset under
 * `public/`) and `Settings.jsx` documents that honestly, so it is left alone.
 */
function useDocumentTitle(appName) {
    useEffect(() => {
        if (!appName) return;
        const previous = document.title;
        document.title = appName;
        return () => {
            document.title = previous;
        };
    }, [appName]);
}

export function useBranding() {
    const query = useQuery({
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

    useDocumentTitle(query.data?.appName);

    return query;
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
