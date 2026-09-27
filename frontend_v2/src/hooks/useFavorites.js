import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import { settingsApi } from '../api/settingsApi';

const EMPTY_ARRAY = [];

export function useFavorites() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ['favorites'],
    queryFn: async () => {
      const res = await settingsApi.getFavorites();
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
      queryClient.setQueryData(['favorites'], context.previousFavorites);
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
    const current = queryClient.getQueryData(['favorites']) || favorites;
    const isFav = current.includes(filename);
    const newFavorites = isFav ? current.filter(f => f !== filename) : [...current, filename];
    mutate(newFavorites);
  }, [favorites, mutate, queryClient]);

  const isFavorite = useCallback((filename) => {
    return favorites.includes(filename);
  }, [favorites]);

  return {
    favorites,
    isLoading: query.isLoading,
    toggleFavorite,
    isFavorite,
  };
}
