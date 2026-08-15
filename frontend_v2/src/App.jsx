/**
 * App.jsx - Root application component
 *
 * ARCHITECTURE OVERVIEW:
 *   - Routing: React Router v6 with lazy-loaded page components to minimise
 *     the initial JS bundle.  AnimatePresence wraps route transitions for
 *     smooth page animations via Framer Motion.
 *   - State: Zustand stores (settingsStore) are initialised
 *     here for global realtime flows. Provider server-state is owned by React
 *     Query hooks consumed by layout/pages.
 *   - Data fetching: React Query (QueryClient) provides server-state caching.
 *   - Global UI overlays:
 *       ErrorBoundary → QueryClientProvider → Router → Layout → ConfirmationHost
 *   - Notifications: react-hot-toast for user-facing toasts; positioned
 *     top-right with a dark theme matching the overall UI.
 */

import { Suspense, lazy, useEffect, useRef, useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, Outlet } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { AnimatePresence } from 'framer-motion';
import { Toaster } from 'react-hot-toast';
import Layout from './components/Layout';
import ConfirmationHost from './components/ConfirmationHost';
import ErrorBoundary from './components/ErrorBoundary';
import useSettingsStore from './store/settingsStore';
import { useSettings } from './store/settingsStore';
import { migrateLegacyCollections } from './hooks/useCollections';
import { useViewportHeight } from './hooks/useViewportHeight';
import { useJobsRealtime } from './hooks/useJobsRealtime';
import { api } from './api';
// Lazy-loaded pages to minimise initial JS bundle
const FantasyHub = lazy(() => import('./pages/FantasyHub'));
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
const Characters = lazy(() => import('./pages/Characters'));
const ChatWorkspace = lazy(() => import('./pages/ChatWorkspace'));
const StorySandbox = lazy(() => import('./pages/StorySandbox'));
const StoryReader = lazy(() => import('./pages/StoryReader'));
const Scenarios = lazy(() => import('./pages/Scenarios'));
const Voices = lazy(() => import('./pages/Voices'));
const WorldVaultHub = lazy(() => import('./pages/WorldVaultHub'));
const Locations = lazy(() => import('./pages/Locations'));
const AvatarGallery = lazy(() => import('./pages/AvatarGallery'));
const BatchGenerate = lazy(() => import('./pages/BatchGenerate'));
const WorldTimeline = lazy(() => import('./pages/WorldTimeline'));
const Campaigns = lazy(() => import('./pages/Campaigns'));
const RelationshipGraph = lazy(() => import('./pages/RelationshipGraph'));

function AnimatedRoutes() {
    const location = useLocation();
    // Collapse dynamic segments into a stable key so param-only navigations
    // (e.g. /chat -> /chat/:chatId) don't remount the page component, which
    // would destroy transient UI state (open modals, composer drafts, etc.).
    const routeKey = (() => {
        const parts = location.pathname.split('/').filter(Boolean);
        if (parts[0] === 'chat' || parts[0] === 'story') return `/${parts[0]}`;
        return location.pathname;
    })();
    return (
        <AnimatePresence mode="wait">
            <Routes location={location} key={routeKey}>
                <Route path="/" element={<ErrorBoundary><FantasyHub /></ErrorBoundary>} />
                <Route path="/gallery" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
                <Route path="/generate" element={<ErrorBoundary><SimpleGenerator /></ErrorBoundary>} />
                <Route path="/img2img" element={<ErrorBoundary><Img2ImgGenerator /></ErrorBoundary>} />
                <Route path="/inpaint" element={<ErrorBoundary><InpaintGenerator /></ErrorBoundary>} />
                <Route path="/advanced" element={<ErrorBoundary><AdvancedGenerator /></ErrorBoundary>} />
                <Route path="/chat" element={<Outlet />}>
                    <Route index element={<ErrorBoundary><ChatWorkspace /></ErrorBoundary>} />
                    <Route path=":chatId" element={<ErrorBoundary><ChatWorkspace /></ErrorBoundary>} />
                </Route>
                <Route path="/story" element={<Outlet />}>
                    <Route index element={<ErrorBoundary><StorySandbox /></ErrorBoundary>} />
                    <Route path=":storyId" element={<ErrorBoundary><StorySandbox /></ErrorBoundary>} />
                    <Route path=":storyId/chapter/:chapterId" element={<ErrorBoundary><StorySandbox /></ErrorBoundary>} />
                </Route>
                <Route path="/characters" element={<ErrorBoundary><Characters /></ErrorBoundary>} />
                <Route path="/scenarios" element={<ErrorBoundary><Scenarios /></ErrorBoundary>} />
                <Route path="/voices" element={<ErrorBoundary><Voices /></ErrorBoundary>} />
                <Route path="/world-vault" element={<ErrorBoundary><WorldVaultHub /></ErrorBoundary>} />
                <Route path="/locations" element={<ErrorBoundary><Locations /></ErrorBoundary>} />
                <Route path="/avatar-gallery" element={<ErrorBoundary><AvatarGallery /></ErrorBoundary>} />
                <Route path="/batch-generate" element={<ErrorBoundary><BatchGenerate /></ErrorBoundary>} />
                <Route path="/world-timeline" element={<ErrorBoundary><WorldTimeline /></ErrorBoundary>} />
                <Route path="/campaigns" element={<ErrorBoundary><Campaigns /></ErrorBoundary>} />
                <Route path="/world-graph" element={<ErrorBoundary><RelationshipGraph /></ErrorBoundary>} />
                <Route path="/read/story/:token" element={<ErrorBoundary><StoryReader /></ErrorBoundary>} />
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

    // One-time legacy localStorage -> API collections migration (runs at most
    // once; flag-gated inside). Kept out of the query path so collection
    // refetches never re-trigger migration work.
    useEffect(() => {
        migrateLegacyCollections().catch((error) => {
            console.warn('Failed to migrate legacy collections:', error);
        });
    }, []);

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

        const current = queryClient.getDefaultOptions().queries;
        if (current.staleTime === staleTime && current.gcTime === gcTime) {
            return;
        }

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
