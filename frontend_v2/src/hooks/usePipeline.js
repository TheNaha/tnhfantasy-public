import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, API_V2_BASE } from '../api';

export const PIPELINE_KEY = ['llm', 'pipeline'];
export const PIPELINE_QUESTIONS_KEY = ['llm', 'questions'];
export const DIRECTOR_TRACES_KEY = (chatId) => ['llm', 'director-traces', chatId];

export function usePipeline() {
    return useQuery({
        queryKey: PIPELINE_KEY,
        queryFn: ({ signal }) => api.get(`${API_V2_BASE}/llm/pipeline`, { signal }),
        staleTime: 60_000,
    });
}

export function usePipelineQuestions() {
    return useQuery({
        queryKey: PIPELINE_QUESTIONS_KEY,
        queryFn: ({ signal }) => api.get(`${API_V2_BASE}/llm/questions`, { signal }),
        staleTime: 30_000,
    });
}

export function useUpdateQuestionOverride() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ stage, key, updates }) =>
            api.put(`${API_V2_BASE}/llm/questions/${stage}/${key}`, updates),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: PIPELINE_QUESTIONS_KEY });
        },
    });
}

export function useCreateCustomQuestion() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ stage, question }) =>
            api.post(`${API_V2_BASE}/llm/questions/${stage}/custom`, question),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: PIPELINE_QUESTIONS_KEY });
        },
    });
}

export function useDeleteQuestionOverride() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ stage, key }) =>
            api.delete(`${API_V2_BASE}/llm/questions/${stage}/${key}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: PIPELINE_QUESTIONS_KEY });
        },
    });
}

export function useDirectorTraces(chatId) {
    return useQuery({
        queryKey: DIRECTOR_TRACES_KEY(chatId),
        queryFn: ({ signal }) => api.get(`${API_V2_BASE}/chats/${chatId}/director-traces`, { signal }),
        enabled: !!chatId,
        staleTime: 10_000,
    });
}
