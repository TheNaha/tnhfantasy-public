/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';

const BrandingContext = createContext(null);

export function BrandingProvider({ children }) {
    const { data: branding, isLoading } = useQuery({
        queryKey: ['branding'],
        queryFn: async () => {
            try {
                return await api.get('/api/settings/branding');
            } catch {
                // Return defaults if API fails
                return {
                    appName: "TNH Comfy Gen",
                    logoUrl: "/logo.png",
                    faviconUrl: "/favicon.ico"
                };
            }
        },
        staleTime: 5 * 60 * 1000, // 5 minutes
        cacheTime: 10 * 60 * 1000, // 10 minutes
    });

    // Default branding while loading
    const currentBranding = branding || {
        appName: "TNH Comfy Gen",
        logoUrl: "/logo.png",
        faviconUrl: "/favicon.ico"
    };

    return (
        <BrandingContext.Provider value={{ branding: currentBranding, isLoading }}>
            {children}
        </BrandingContext.Provider>
    );
}

export function useBranding() {
    const context = useContext(BrandingContext);
    if (!context) {
        throw new Error('useBranding must be used within a BrandingProvider');
    }
    return context;
}
