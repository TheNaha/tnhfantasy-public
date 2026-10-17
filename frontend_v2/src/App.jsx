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

import { Suspense, lazy, useEffect, useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, useParams, Outlet } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { AnimatePresence, MotionConfig } from 'framer-motion';
import { Toaster, toast } from 'react-hot-toast';
import Layout from './components/Layout';
import ConfirmationHost from './components/ConfirmationHost';
import ErrorBoundary from './components/ErrorBoundary';
import { ChatRouteGuard, StoryRouteGuard } from './components/RouteQueryGuard';
import useSettingsStore from './store/settingsStore';
import { useShallow } from 'zustand/react/shallow';
import { migrateLegacyCollections } from './hooks/useCollections';
import { useViewportHeight } from './hooks/useViewportHeight';
import { useJobsRealtime } from './hooks/useJobsRealtime';
import * as ws from './api/websocket';
// Lazy-loaded pages to minimise initial JS bundle
const RoleplayWorkspace = lazy(() => import('./pages/RoleplayWorkspace'));
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
const Personas = lazy(() => import('./pages/Personas'));
const Voices = lazy(() => import('./pages/Voices'));
const Lorebooks = lazy(() => import('./pages/Lorebooks'));
const WorldVaultHub = lazy(() => import('./pages/WorldVaultHub'));
const Locations = lazy(() => import('./pages/Locations'));
const BatchGenerate = lazy(() => import('./pages/BatchGenerate'));
const Activity = lazy(() => import('./pages/Activity'));
const Worlds = lazy(() => import('./pages/Worlds'));
const WorldArchitect = lazy(() => import('./pages/WorldArchitect'));
const RelationshipGraph = lazy(() => import('./pages/RelationshipGraph'));
const Prompts = lazy(() => import('./pages/Prompts'));
const NotFound = lazy(() => import('./pages/NotFound'));

// Keyed by routeKey so a crashed page resets when the user navigates away
// (kept at module scope so its identity is stable across renders and
// param-only navigations don't remount the page subtree).
function Boundary({ routeKey, children }) {
    return <ErrorBoundary key={routeKey}>{children}</ErrorBoundary>;
}

function GuardedChat({ children }) {
    const { chatId } = useParams();
    return <ChatRouteGuard chatId={chatId}>{children}</ChatRouteGuard>;
}

function GuardedStory({ children }) {
    const { storyId } = useParams();
    return <StoryRouteGuard storyId={storyId}>{children}</StoryRouteGuard>;
}

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
                {/* One front door. `/` used to be the Fantasy Hub workspace picker,
                    which made a workspace index the landing page for an app whose
                    whole premise is roleplay-first — and left two competing landing
                    pages with different design languages.

                    The picker is now deleted rather than parked at a second URL.
                    It had no nav entry and no inbound link anywhere, and its one
                    unique job — hosting the first-run onboarding wizard — is
                    mounted on /roleplay, so nothing about first-run setup depended
                    on it. A second front door that nothing links to is still a
                    second front door. */}
                <Route path="/" element={<Navigate to="/roleplay" replace />} />
                <Route path="/roleplay" element={<Boundary routeKey={routeKey}><RoleplayWorkspace /></Boundary>} />
                <Route path="/gallery" element={<Boundary routeKey={routeKey}><Dashboard /></Boundary>} />
                <Route path="/generate" element={<Boundary routeKey={routeKey}><SimpleGenerator /></Boundary>} />
                <Route path="/img2img" element={<Boundary routeKey={routeKey}><Img2ImgGenerator /></Boundary>} />
                <Route path="/inpaint" element={<Boundary routeKey={routeKey}><InpaintGenerator /></Boundary>} />
                <Route path="/advanced" element={<Boundary routeKey={routeKey}><AdvancedGenerator /></Boundary>} />
                <Route path="/chat" element={<Outlet />}>
                    <Route index element={<Boundary routeKey={routeKey}><ChatWorkspace /></Boundary>} />
                    <Route path=":chatId" element={<Boundary routeKey={routeKey}><GuardedChat><ChatWorkspace /></GuardedChat></Boundary>} />
                </Route>
                <Route path="/story" element={<Outlet />}>
                    <Route index element={<Boundary routeKey={routeKey}><StorySandbox /></Boundary>} />
                    <Route path=":storyId" element={<Boundary routeKey={routeKey}><GuardedStory><StorySandbox /></GuardedStory></Boundary>} />
                    <Route path=":storyId/chapter/:chapterId" element={<Boundary routeKey={routeKey}><GuardedStory><StorySandbox /></GuardedStory></Boundary>} />
                </Route>
                <Route path="/characters" element={<Boundary routeKey={routeKey}><Characters /></Boundary>} />
                <Route path="/scenarios" element={<Boundary routeKey={routeKey}><Scenarios /></Boundary>} />
                <Route path="/personas" element={<Boundary routeKey={routeKey}><Personas /></Boundary>} />
                <Route path="/voices" element={<Boundary routeKey={routeKey}><Voices /></Boundary>} />
                <Route path="/lorebooks" element={<Boundary routeKey={routeKey}><Lorebooks /></Boundary>} />
                <Route path="/world-vault" element={<Boundary routeKey={routeKey}><WorldVaultHub /></Boundary>} />
                <Route path="/locations" element={<Boundary routeKey={routeKey}><Locations /></Boundary>} />
                {/* Retired. The Avatar Gallery was this page's grid again with
                    the edit actions stripped off, so it owned no data and no
                    capability that could not live here. Redirected rather than
                    404'd so any bookmark keeps working. */}
                <Route path="/avatar-gallery" element={<Navigate to="/characters" replace />} />
                <Route path="/batch-generate" element={<Boundary routeKey={routeKey}><BatchGenerate /></Boundary>} />
                <Route path="/activity" element={<Boundary routeKey={routeKey}><Activity /></Boundary>} />
                {/* Kept as an alias: the page was called "World Timeline" and is now
                    "Activity", and bookmarks should survive a rename. */}
                <Route path="/world-timeline" element={<Navigate to="/activity" replace />} />
                {/* Kept as an alias: `a338abc0` renamed the server-side Campaign
                    resource to World, and this is the third redirect kept for a
                    retired URL (see /avatar-gallery and /world-timeline). The
                    page itself was rewritten, not just repointed — the old one had
                    no `isError` branch, so the 404 behind `/api/v2/campaigns`
                    rendered as a plausible empty vault. */}
                <Route path="/campaigns" element={<Navigate to="/worlds" replace />} />
                <Route path="/worlds" element={<Boundary routeKey={routeKey}><Worlds /></Boundary>} />
                <Route path="/world-architect" element={<Boundary routeKey={routeKey}><WorldArchitect /></Boundary>} />
                <Route path="/world-graph" element={<Boundary routeKey={routeKey}><RelationshipGraph /></Boundary>} />
                <Route path="/prompts" element={<Boundary routeKey={routeKey}><Prompts /></Boundary>} />
                <Route path="/read/story/:token" element={<Boundary routeKey={routeKey}><StoryReader /></Boundary>} />
                <Route path="/models/discover" element={<Boundary routeKey={routeKey}><DiscoverModels /></Boundary>} />
                <Route path="/models/installed" element={<Boundary routeKey={routeKey}><InstalledModels /></Boundary>} />
                <Route path="/models" element={<Navigate to="/models/installed" replace />} />
                <Route path="/providers" element={<Boundary routeKey={routeKey}><Providers /></Boundary>} />
                <Route path="/statistics" element={<Boundary routeKey={routeKey}><Statistics /></Boundary>} />
                <Route path="/settings" element={<Boundary routeKey={routeKey}><Settings /></Boundary>} />
                <Route path="*" element={<Boundary routeKey={routeKey}><NotFound /></Boundary>} />
            </Routes>
        </AnimatePresence>
    );
}

function GlobalHooks() {
    // Initialize dynamic viewport height for iOS Safari
    useViewportHeight();
    
    // Initialize global job notifications and WebSocket sync
    useJobsRealtime();

    // Subscribe to backend events that have no dedicated page-level handler.
    // There used to be a matching set of `download.*` handlers here; that family
    // never had a producer in the backend, so it was removed from both sides
    // rather than left looking like push-based download progress already works.
    // Model-download status is polled instead.
    useEffect(() => {
        let mounted = true;
        const topics = ['model'];
        ws.subscribe(topics).catch((error) => {
            if (mounted) console.warn('Failed to subscribe global realtime topics:', error);
        });
        const unsubs = [];
        const toastFor = (label, event) => {
            if (event.type?.endsWith('.completed')) {
                toast.success(`${label} completed`);
            } else if (event.type?.endsWith('.failed')) {
                toast.error(`${label} failed`);
            } else if (event.type?.endsWith('.started')) {
                toast.loading(`${label} started...`, { id: label });
            }
        };

        unsubs.push(ws.on(ws.EventTypes.MODEL_SYNC_STARTED, (e) => toastFor('Model sync', e)));
        unsubs.push(ws.on(ws.EventTypes.MODEL_SYNC_COMPLETED, (e) => toastFor('Model sync', e)));
        unsubs.push(ws.on(ws.EventTypes.MODEL_SYNC_FAILED, (e) => toastFor('Model sync', e)));
        // `services/in_process_reconciliation` emits this now, and the number is
        // the fraction of the QUEUE that has been drained, not of the file in
        // flight: `engines.base.download_file` awaits a single remote call with
        // no per-byte callback, so "this checkpoint is 40% down" is not
        // observable from the backend and must not be implied. The event carries
        // `progress_scope: 'batch'` for exactly this reason, and the copy below
        // says it.
        //
        // Keyed by provider+directory so a burst for one provider's sync replaces
        // its own toast instead of stacking.
        unsubs.push(ws.on(ws.EventTypes.MODEL_SYNC_PROGRESS, (event) => {
            const d = event?.data || {};
            const pct = typeof d.progress === 'number' ? Math.round(d.progress) : null;
            const label = d.model_name || d.directory || 'models';
            const done = typeof d.completed === 'number' ? d.completed : null;
            const total = typeof d.total === 'number' ? d.total : null;
            const counts = done !== null && total !== null ? ` · ${done}/${total}` : '';
            toast.loading(
                pct === null
                    ? `Syncing ${label}...`
                    : `Syncing ${label} — ${pct}%${counts}`,
                { id: `sync-progress:${d.provider_id || ''}:${d.directory || ''}` },
            );
        }));

        return () => {
            mounted = false;
            unsubs.forEach((fn) => { try { fn(); } catch { /* ignore */ } });
            ws.unsubscribe(topics);
        };
    }, []);

    // One-time legacy localStorage -> API collections migration (runs at most
    // once; flag-gated inside). Kept out of the query path so collection
    // refetches never re-trigger migration work.
    useEffect(() => {
        migrateLegacyCollections().catch((error) => {
            console.warn('Failed to migrate legacy collections:', error);
        });
    }, []);


    return null;
}

function App() {
    const queryUiSettings = useSettingsStore((state) => state.settings.ui);
    // Settings > UI > "Animation Duration": the only global handle on how fast
    // Framer Motion animates, since every page transition reads the default
    // transition rather than declaring its own.
    const animationDuration = Number.isFinite(queryUiSettings?.animationDuration)
        ? queryUiSettings.animationDuration
        : 300;
    const toastDurations = useSettingsStore(useShallow((state) => ({
        success: state.settings.ui.toastSuccessDuration,
        error: state.settings.ui.toastErrorDuration,
    })));

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
                    // NOT 1. react-query v5 applies the mutation retry to every
                    // mutation regardless of method and does not filter by
                    // status class, so a retry on a lost response re-sent every
                    // non-idempotent POST and DELETE in the app: a second job
                    // from /jobs/:id/retry, a duplicated chat message and a
                    // duplicated LLM call from send, a duplicate character, and
                    // a DELETE that succeeded server-side then reported "Failed
                    // to remove job" on its 404. Only /api/generate* send an
                    // Idempotency-Key. Opt individual mutations back in where a
                    // retry is actually safe.
                    retry: 0,
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

        // This effect exists only to apply the two user-configurable cache
        // timings. It must not restate the rest of the policy: `setDefaultOptions`
        // REPLACES both sub-objects wholesale, so the version that also passed
        // `mutations: { retry: 1 }` undid the constructor's `retry: 0` on every
        // page load — re-enabling retried non-idempotent POST/DELETEs (duplicate
        // jobs, duplicated chat messages and paid LLM calls, duplicate
        // characters, and DELETEs that succeeded then reported a 404 failure).
        // The guard above also never matched on mount, because the constructor
        // hardcodes a 30-minute gcTime while the store default is 10 — so the
        // overwrite was unconditional, not an edge case.
        //
        // Merging keeps `mutations` exactly as the constructor set it, and means
        // a future default added here survives a settings change too.
        queryClient.setDefaultOptions({
            ...queryClient.getDefaultOptions(),
            queries: {
                ...current,
                staleTime,
                gcTime,
            },
        });
    }, [queryClient, queryUiSettings]);

    return (
        <ErrorBoundary>
            <MotionConfig transition={{ duration: animationDuration / 1000 }}>
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
                                duration: toastDurations.success,
                                iconTheme: {
                                    primary: '#10b981',
                                    secondary: '#1f2937',
                                },
                            },
                            error: {
                                duration: toastDurations.error,
                                iconTheme: {
                                    primary: '#ef4444',
                                    secondary: '#1f2937',
                                },
                            },
                        }}
                    />
                </QueryClientProvider>
            </MotionConfig>
        </ErrorBoundary>
    );
}

export default App;
