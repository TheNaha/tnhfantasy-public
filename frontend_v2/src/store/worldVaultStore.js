import { create } from 'zustand';

// Chat/story selection is driven by URL params (deep-linking); the store only
// mirrors the currently open chat so navigation between pages can restore it.
export const useWorldVaultStore = create((set) => ({
  activeChatId: null,

  setActiveChat: (chatId) => set({ activeChatId: chatId }),
}));
