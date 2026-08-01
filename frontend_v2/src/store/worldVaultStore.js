import { create } from 'zustand';

export const useWorldVaultStore = create((set) => ({
  activeChatId: null,
  activeCharacterId: null,
  activeScenarioId: null,
  
  // UI state for Context Builder
  contextBuilder: {
    selectedLorebooks: [],
    systemPromptOverride: null,
    maxContextTokens: 4096,
  },
  
  setActiveChat: (chatId) => set({ activeChatId: chatId }),
  setActiveCharacter: (characterId) => set({ activeCharacterId: characterId }),
  setActiveScenario: (scenarioId) => set({ activeScenarioId: scenarioId }),
  
  toggleLorebook: (lorebookId) => set((state) => {
    const selected = state.contextBuilder.selectedLorebooks;
    const isSelected = selected.includes(lorebookId);
    return {
      contextBuilder: {
        ...state.contextBuilder,
        selectedLorebooks: isSelected 
          ? selected.filter(id => id !== lorebookId)
          : [...selected, lorebookId]
      }
    };
  }),
  
  setSystemPrompt: (prompt) => set((state) => ({
    contextBuilder: { ...state.contextBuilder, systemPromptOverride: prompt }
  })),
  
  resetContext: () => set(() => ({
    contextBuilder: {
      selectedLorebooks: [],
      systemPromptOverride: null,
      maxContextTokens: 4096,
    }
  }))
}));
