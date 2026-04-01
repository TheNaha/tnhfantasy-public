import { create } from 'zustand';
import { api } from '../api';

const DEFAULT_BRANDING = {
    appName: 'TNH-Comfy',
    logoUrl: '/logo.png',
    faviconUrl: '/favicon.ico',
};

export const useBrandingStore = create((set, get) => ({
    branding: DEFAULT_BRANDING,
    isLoading: false,
    initialized: false,

    loadBranding: async ({ force = false } = {}) => {
        const { initialized, isLoading } = get();
        if (!force && (initialized || isLoading)) {
            return get().branding;
        }

        set({ isLoading: true });
        try {
            const branding = await api.get('/api/settings/branding');
            const nextBranding = {
                appName: branding?.appName || DEFAULT_BRANDING.appName,
                logoUrl: branding?.logoUrl || DEFAULT_BRANDING.logoUrl,
                faviconUrl: branding?.faviconUrl || DEFAULT_BRANDING.faviconUrl,
            };
            set({ branding: nextBranding, isLoading: false, initialized: true });
            return nextBranding;
        } catch {
            set({ isLoading: false, initialized: true });
            return get().branding;
        }
    },

    saveBranding: async (branding) => {
        const payload = {
            appName: branding?.appName || DEFAULT_BRANDING.appName,
            logoUrl: branding?.logoUrl || DEFAULT_BRANDING.logoUrl,
            faviconUrl: branding?.faviconUrl || DEFAULT_BRANDING.faviconUrl,
        };
        await api.post('/api/settings/branding', payload);
        set({ branding: payload, initialized: true });
        return payload;
    },
}));
