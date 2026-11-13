import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import { settingsApi } from '../api/settingsApi';
import toast from 'react-hot-toast';

const EMPTY_ARRAY = [];

export function useFavorites() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ['favorites'],
    queryFn: async ({ signal }) => {
      const res = await settingsApi.getFavorites({ signal });
      return res.favorites || [];
    },
  });

  const mutation = useMutation({
    scope: { id: 'favorites' },
    mutationFn: async (newFavorites) => {
      const res = await settingsApi.updateFavorites(newFavorites);
      return res.favorites;
    },
    onMutate: (newFavorites) => {
      const previousFavorites = queryClient.getQueryData(['favorites']);
      queryClient.setQueryData(['favorites'], newFavorites);
      return { previousFavorites };
    },
    onError: (err, newFavorites, context) => {
      queryClient.setQueryData(['favorites'], context?.previousFavorites);
      toast.error(err?.message ? `Failed to update favorites: ${err.message}` : 'Failed to update favorites');
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['favorites'] });
    },
  });

  const favorites = query.data || EMPTY_ARRAY;
  // `mutation` is a fresh object from useMutation on every render, so it must
  // not be a useCallback dep: it made `toggleFavorite` (and the memoised
  // dashboard components behind it) re-render on every parent render.
  const { mutate } = mutation;

  const toggleFavorite = useCallback((filename) => {
    const current = queryClient.getQueryData(['favorites']) || EMPTY_ARRAY;
    const isFav = current.includes(filename);
    const newFavorites = isFav ? current.filter(f => f !== filename) : [...current, filename];
    mutate(newFavorites);
  }, [mutate, queryClient]);

  // Bulk add in ONE write.
  //
  // The endpoint is a whole-list overwrite (`settingsApi.updateFavorites` POSTs
  // the entire array), so `toggleFavorite` is a read-modify-write. `mutate()`
  // runs `onMutate` asynchronously, so calling it N times in a synchronous
  // loop — which is exactly what the gallery's batch-favourite did — meant every
  // iteration read the same pre-batch list and computed the same
  // "base + one image" result. The server received N overwrites, last one won,
  // and only one image out of N was actually favourited while the UI reported
  // "Added N images to favorites". The subsequent `onSettled` invalidation then
  // quietly corrected the UI to 1, so the failure was invisible.
  const addFavorites = useCallback((filenames) => {
    const additions = filenames.filter(Boolean);
    if (additions.length === 0) return;
    const current = queryClient.getQueryData(['favorites']) || favorites || [];
    const merged = [...current];
    for (const filename of additions) {
      if (!merged.includes(filename)) merged.push(filename);
    }
    mutate(merged);
  }, [favorites, mutate, queryClient]);

  const isFavorite = useCallback((filename) => {
    return favorites.includes(filename);
  }, [favorites]);

  return {
    favorites,
    isLoading: query.isLoading,
    toggleFavorite,
    addFavorites,
    isFavorite,
  };
}
