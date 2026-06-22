import { create } from 'zustand';

const DEFAULT_BRANDING = {
    appName: 'TNH-Comfy',
    logoUrl: '/logo.png',
    faviconUrl: '/favicon.ico',
};

export const useBrandingStore = create((set) => ({
    branding: DEFAULT_BRANDING,
    isLoading: false,
    initialized: false,

    setBranding: (branding) => set({
        branding,
        isLoading: false,
        initialized: true,
    }),

    setLoading: (isLoading) => set({ isLoading }),
}));
