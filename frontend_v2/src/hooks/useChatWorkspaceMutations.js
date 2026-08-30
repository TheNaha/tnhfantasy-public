import { useMemo } from 'react';
import {
    useSendMessage, useCreateChat, useDeleteChat, useRenameChat, useUpdateChat,
    useSuggestReply, useEditMessage, useRollbackChat, useRegenerateReply,
    usePatchCharacter, useImpersonateMessage, usePinMessage, useSwipeMessage,
    useGenerateSwipe, useIllustrateChat, useGenerateScene, useNarrateMessage,
    useDeleteMessage, useExportChatJsonl, useImportChat,
} from '../hooks/useWorldVault';

/**
 * Centralizes all mutation hooks for the chat workspace so the provider stays
 * focused on local UI state and action handlers.
 * Returns the mutation objects keyed by the same names the provider has always
 * exposed.
 */
export function useChatWorkspaceMutations() {
    const sendMessageMutation = useSendMessage();
    const createChatMutation = useCreateChat();
    const exportJsonlMutation = useExportChatJsonl();
    const importChatMutation = useImportChat();
    const deleteChatMutation = useDeleteChat();
    const renameChatMutation = useRenameChat();
    const updateChatMutation = useUpdateChat();
    const editMessageMutation = useEditMessage();
    const rollbackMutation = useRollbackChat();
    const regenerateMutation = useRegenerateReply();
    const patchCharacterMutation = usePatchCharacter();
    const deleteMessageMutation = useDeleteMessage();
    const impersonateMutation = useImpersonateMessage();
    const pinMessageMutation = usePinMessage();
    const swipeMessageMutation = useSwipeMessage();
    const generateSwipeMutation = useGenerateSwipe();
    const narrateMutation = useNarrateMessage();
    const illustrateMutation = useIllustrateChat();
    const generateSceneMutation = useGenerateScene();
    const suggestReplyMutation = useSuggestReply();

    return useMemo(() => ({
        sendMessageMutation,
        createChatMutation,
        exportJsonlMutation,
        importChatMutation,
        deleteChatMutation,
        renameChatMutation,
        updateChatMutation,
        editMessageMutation,
        rollbackMutation,
        regenerateMutation,
        patchCharacterMutation,
        deleteMessageMutation,
        impersonateMutation,
        pinMessageMutation,
        swipeMessageMutation,
        generateSwipeMutation,
        narrateMutation,
        illustrateMutation,
        generateSceneMutation,
        suggestReplyMutation,
    }), [
        sendMessageMutation, createChatMutation, exportJsonlMutation, importChatMutation,
        deleteChatMutation, renameChatMutation, updateChatMutation, editMessageMutation,
        rollbackMutation, regenerateMutation, patchCharacterMutation, deleteMessageMutation,
        impersonateMutation, pinMessageMutation, swipeMessageMutation, generateSwipeMutation,
        narrateMutation, illustrateMutation, generateSceneMutation, suggestReplyMutation,
    ]);
}
