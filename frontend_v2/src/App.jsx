/**
 * App.jsx - Root application component
 *
 * ARCHITECTURE OVERVIEW:
 *   - Routing: React Router v6 with lazy-loaded page components to minimise
 *     the initial JS bundle.  AnimatePresence wraps route transitions for
 *     smooth page animations via Framer Motion.
 *   - State: Zustand stores (jobStore) are initialised
 *     here for global realtime flows. Provider server-state is owned by React
 *     Query hooks consumed by layout/pages.
 *   - Data fetching: React Query (QueryClient) provides server-state caching.
 *   - Global UI overlays:
 *       ErrorBoundary → QueryClientProvider → Router → Layout → ConfirmationHost
 *   - Notifications: react-hot-toast for user-facing toasts; positioned
 *     top-right with a dark theme matching the overall UI.
 */

import { Suspense, lazy, useEffect, useRef, useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { AnimatePresence } from 'framer-motion';
import { Toaster } from 'react-hot-toast';
import Layout from './components/Layout';
import ConfirmationHost from './components/ConfirmationHost';
import ErrorBoundary from './components/ErrorBoundary';
import useSettingsStore from './store/settingsStore';
import { useBrandingStore } from './store/brandingStore';
import { useBranding } from './hooks/useBranding';
import { useSettings } from './store/settingsStore';
import { useViewportHeight } from './hooks/useViewportHeight';
import { useJobsRealtime } from './hooks/useJobsRealtime';
import { api } from './api';
// Lazy-loaded pages to minimise initial JS bundle
const Dashboard = lazy(() => import('./pages/Dashboard'));
const SimpleGenerator = lazy(() => import('./pages/SimpleGenerator'));
const AdvancedGenerator = lazy(() => import('./pages/AdvancedGenerator'));
const Img2ImgGenerator = lazy(() => import('./pages/Img2ImgGenerator'));
const InpaintGenerator = lazy(() => import('./pages/InpaintGenerator'));
const DiscoverModels = lazy(() => import('./pages/DiscoverModels'));
const InstalledModels = lazy(() => import('./pages/InstalledModels'));
const Statistics = lazy(() => import('./pages/Statistics'));
const Settings = lazy(() => import('./pages/Settings'));
const Providers = lazy(() => import('./pages/Providers'));

function AnimatedRoutes() {
    const location = useLocation();
    return (
        <AnimatePresence mode="wait">
            <Routes location={location} key={location.pathname}>
                <Route path="/" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
                <Route path="/generate" element={<ErrorBoundary><SimpleGenerator /></ErrorBoundary>} />
                <Route path="/img2img" element={<ErrorBoundary><Img2ImgGenerator /></ErrorBoundary>} />
                <Route path="/inpaint" element={<ErrorBoundary><InpaintGenerator /></ErrorBoundary>} />
                <Route path="/advanced" element={<ErrorBoundary><AdvancedGenerator /></ErrorBoundary>} />
                <Route path="/models/discover" element={<ErrorBoundary><DiscoverModels /></ErrorBoundary>} />
                <Route path="/models/installed" element={<ErrorBoundary><InstalledModels /></ErrorBoundary>} />
                <Route path="/models" element={<Navigate to="/models/installed" replace />} />
                <Route path="/providers" element={<ErrorBoundary><Providers /></ErrorBoundary>} />
                <Route path="/statistics" element={<ErrorBoundary><Statistics /></ErrorBoundary>} />
                <Route path="/settings" element={<ErrorBoundary><Settings /></ErrorBoundary>} />
                <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
        </AnimatePresence>
    );
}

function GlobalHooks() {
    // Initialize dynamic viewport height for iOS Safari
    // This sets --vh CSS variable that works correctly with address bar
    useViewportHeight();
    
    // Initialize global job notifications and WebSocket sync
    useJobsRealtime();

    // Gate to ensure provider wake is only called once per mount
    const hasRequestedProviderWake = useRef(false);

    useEffect(() => {
        if (hasRequestedProviderWake.current) {
            return;
        }
        hasRequestedProviderWake.current = true;

        api.post('/api/providers/wake').catch((error) => {
            console.warn('Failed to warm providers:', error);
        });
    }, []);

    return null;
}

function App() {
    const queryUiSettings = useSettingsStore((state) => state.settings?.ui);
    const setBranding = useBrandingStore((state) => state.setBranding);
    const { data: branding } = useBranding();
    const settings = useSettings();

    const [queryClient] = useState(() => (
        new QueryClient({
            defaultOptions: {
                queries: {
                    staleTime: 1000 * 60 * 5,
                    gcTime: 1000 * 60 * 30,
                    retry: 1,
                    refetchOnWindowFocus: false,
                    refetchOnReconnect: true,
                    networkMode: 'online',
                },
                mutations: {
                    retry: 1,
                    networkMode: 'online',
                },
            },
        })
    ));

    useEffect(() => {
        const staleTime = Number.isFinite(queryUiSettings?.queryStaleTime)
            ? queryUiSettings.queryStaleTime
            : 1000 * 60 * 5;
        const gcTime = Number.isFinite(queryUiSettings?.queryCacheTime)
            ? queryUiSettings.queryCacheTime
            : 1000 * 60 * 30;

        queryClient.setDefaultOptions({
            queries: {
                staleTime,
                gcTime,
                retry: 1,
                refetchOnWindowFocus: false,
                refetchOnReconnect: true,
                networkMode: 'online',
            },
            mutations: {
                retry: 1,
                networkMode: 'online',
            },
        });
    }, [queryClient, queryUiSettings]);

    useEffect(() => {
        if (branding) {
            setBranding(branding);
        }
    }, [branding, setBranding]);

    return (
        <ErrorBoundary>
            <QueryClientProvider client={queryClient}>
                <GlobalHooks />
                <Router>
                    <Layout>
                        <Suspense fallback={
                            <div className="flex items-center justify-center h-screen bg-gray-900">
                                <Loader2 className="animate-spin text-blue-500" size={48} />
                            </div>
                        }>
                            <AnimatedRoutes />
                        </Suspense>
                    </Layout>
                </Router>
                <ConfirmationHost />
                <Toaster
                    position="top-right"
                    toastOptions={{
                        className: '',
                        style: {
                            background: '#1f2937',
                            color: '#f3f4f6',
                            border: '1px solid #374151',
                        },
                        success: {
                            duration: settings.ui.toastSuccessDuration,
                            iconTheme: {
                                primary: '#10b981',
                                secondary: '#1f2937',
                            },
                        },
                        error: {
                            duration: settings.ui.toastErrorDuration,
                            iconTheme: {
                                primary: '#ef4444',
                                secondary: '#1f2937',
                            },
                        },
                    }}
                />
            </QueryClientProvider>
        </ErrorBoundary>
    );
}

export default App;
