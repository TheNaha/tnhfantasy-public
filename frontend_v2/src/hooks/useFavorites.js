import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export function useFavorites() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ['favorites'],
    queryFn: async () => {
      const res = await api.get('/api/settings/favorites');
      return res.favorites || [];
    },
  });

  const mutation = useMutation({
    mutationFn: async (newFavorites) => {
      const res = await api.post('/api/settings/favorites', { favorites: newFavorites });
      return res.favorites;
    },
    onMutate: async (newFavorites) => {
      await queryClient.cancelQueries({ queryKey: ['favorites'] });
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

  const toggleFavorite = (filename) => {
    const current = query.data || [];
    const isFav = current.includes(filename);
    const newFavorites = isFav ? current.filter(f => f !== filename) : [...current, filename];
    mutation.mutate(newFavorites);
  };

  const isFavorite = (filename) => {
    return (query.data || []).includes(filename);
  };

  return {
    favorites: query.data || [],
    isLoading: query.isLoading,
    toggleFavorite,
    isFavorite,
  };
}
