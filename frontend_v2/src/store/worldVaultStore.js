import { create } from 'zustand';

/**
 * Minimal cross-component UI state store.
 *
 * `activeChatId` bridges URL-driven chat selection (ChatWorkspaceContext)
 * with component-local state (e.g. Characters.jsx clears it on unmount).
 * Streaming job state was migrated to React Query (useStreamingJobs.js).
 */
export const useWorldVaultStore = create((set) => ({
  activeChatId: null,
  setActiveChat: (chatId) => set({ activeChatId: chatId }),
}));
