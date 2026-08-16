import React, { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useChat } from '../hooks/useChats';
import { useStory } from '../hooks/useStories';

/**
 * RouteQueryGuard - renders children while a detail query is healthy; once the
 * query reports an error (e.g. 404 for a deleted entity), it toasts and
 * redirects to the collection's fallback path. Pass-through so it can wrap
 * route elements without owning their UI.
 */
function RouteQueryGuard({ query, fallbackPath, message, children = null }) {
    const navigate = useNavigate();
    const notifiedRef = useRef(false);

    useEffect(() => {
        if (query.isError && !notifiedRef.current) {
            notifiedRef.current = true;
            toast.error(message);
            navigate(fallbackPath, { replace: true });
        }
    }, [query.isError, navigate, fallbackPath, message]);

    if (query.isError) {
        return null;
    }
    return children;
}

export function ChatRouteGuard({ chatId, children = null }) {
    const query = useChat(chatId);
    return (
        <RouteQueryGuard query={query} fallbackPath="/chat" message="Chat not found or no longer available">
            {children}
        </RouteQueryGuard>
    );
}

export function StoryRouteGuard({ storyId, children = null }) {
    const query = useStory(storyId);
    return (
        <RouteQueryGuard query={query} fallbackPath="/story" message="Story not found or no longer available">
            {children}
        </RouteQueryGuard>
    );
}

export default RouteQueryGuard;