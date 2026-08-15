import { create } from 'zustand';

export const useWorldVaultStore = create((set) => ({
  activeChatId: null,
  setActiveChat: (chatId) => set({ activeChatId: chatId }),
}));
