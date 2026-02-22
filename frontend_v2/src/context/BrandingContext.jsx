import { createContext, useContext } from 'react';
import { useQuery } from '@tanstack/react-query';

const BrandingContext = createContext(null);

export function BrandingProvider({ children }) {
    const { data: branding, isLoading } = useQuery({
        queryKey: ['branding'],
        queryFn: async () => {
            const res = await fetch('/api/settings/branding');
            if (!res.ok) {
                // Return defaults if API fails
                return {
                    appName: "TNH Comfy Gen",
                    logoUrl: "/logo.png",
                    faviconUrl: "/favicon.ico"
                };
            }
            return res.json();
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
