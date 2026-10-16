import { Users, Contact, User, Calendar, GitBranch, MapPin, Sparkles, Mic, BookMarked } from 'lucide-react';

/**
 * Canonical navigation definitions.
 *
 * EXPERT_TOOLS is the advanced entity/world tooling that sits behind a
 * disclosure control on both the sidebar (`components/Layout.jsx`) and the
 * Roleplay front door (`pages/RoleplayWorkspace.jsx`).
 *
 * Those two surfaces used to render the same concept from two hand-maintained
 * lists that had already drifted — Roleplay Home was missing Avatar Gallery and
 * Worlds, and the labels had diverged ("Lorebook" vs "Lorebooks"). Anything
 * added here appears on both, which is the point.
 *
 * It lives in `constants/` rather than in a component module for two reasons:
 * `Layout` must be able to import it without importing a `lazy()`-loaded page
 * (which would pull that page and the onboarding wizard into the eager bundle),
 * and exporting a non-component from a component module trips
 * `react-refresh/only-export-components`.
 */
export const EXPERT_TOOLS = [
    { to: '/characters', label: 'Characters', icon: Users, description: 'Your cast, with appearances and voices', color: 'text-purple-300' },
    { to: '/personas', label: 'Personas', icon: Contact, description: 'Who you are — sets {{user}} and the system prompt', color: 'text-sky-300' },
    { to: '/activity', label: 'Activity', icon: Calendar, description: 'Recent conversations, chapters, and memories', color: 'text-rose-300' },
    { to: '/world-graph', label: 'World Graph', icon: GitBranch, description: 'Explore relationships and connections', color: 'text-indigo-300' },
    { to: '/locations', label: 'Locations', icon: MapPin, description: 'Places, imagery, and atmosphere', color: 'text-amber-300' },
    { to: '/scenarios', label: 'Scenarios', icon: Sparkles, description: 'Reusable starting situations', color: 'text-cyan-300' },
    { to: '/voices', label: 'Voices', icon: Mic, description: 'Narration and TTS voices', color: 'text-pink-300' },
    { to: '/lorebooks', label: 'Lorebooks', icon: BookMarked, description: 'World facts activated in context', color: 'text-emerald-300' },
];
