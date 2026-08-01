import { create } from 'zustand';

export const useWorldVaultStore = create((set) => ({
  activeChatId: null,
  activeCharacterId: null,
  activeScenarioId: null,
  activeStoryId: null,
  
  // UI state for Context Builder
  contextBuilder: {
    selectedLorebooks: [],
    systemPromptOverride: null,
    maxContextTokens: 4096,
  },
  
  setActiveChat: (chatId) => set({ activeChatId: chatId }),
  setActiveCharacter: (characterId) => set({ activeCharacterId: characterId }),
  setActiveScenario: (scenarioId) => set({ activeScenarioId: scenarioId }),
  setActiveStory: (storyId) => set({ activeStoryId: storyId }),
  
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
  })),

  // Track streaming job outputs
  streamingJobs: {}, // { [jobId]: { text: string, status: string, chatId: string, type: string } }
  updateStreamingJob: (jobId, data) => set((state) => ({
    streamingJobs: {
      ...state.streamingJobs,
      [jobId]: {
        ...state.streamingJobs[jobId],
        ...data
      }
    }
  })),
  clearStreamingJob: (jobId) => set((state) => {
    const newJobs = { ...state.streamingJobs };
    delete newJobs[jobId];
    return { streamingJobs: newJobs };
  })
}));
