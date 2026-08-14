import { create } from 'zustand';

export const useWorldVaultStore = create((set) => ({
  activeChatId: null,
  activeStoryId: null,
  activeCharacterId: null,

  setActiveChat: (chatId) => set({ activeChatId: chatId }),
  setActiveStory: (storyId) => set({ activeStoryId: storyId }),
  setActiveCharacter: (characterId) => set({ activeCharacterId: characterId }),
  reset: () => set({ activeChatId: null, activeStoryId: null, activeCharacterId: null }),
}));
