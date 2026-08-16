import React from 'react';
import { Link } from 'react-router-dom';
import { Compass, Home, Search } from 'lucide-react';

export default function NotFound() {
    return (
        <div className="flex flex-col items-center justify-center min-h-screen bg-gray-950 text-white p-6">
            <div className="glass rounded-lg p-10 max-w-md text-center">
                <div className="flex justify-center mb-4">
                    <span className="text-7xl font-black tracking-tighter bg-gradient-to-br from-indigo-400 via-blue-400 to-purple-500 bg-clip-text text-transparent">
                        404
                    </span>
                </div>
                <div className="flex justify-center mb-4">
                    <Compass size={40} className="text-gray-500" />
                </div>
                <h1 className="text-xl font-bold mb-2">Lost in the realms</h1>
                <p className="text-gray-400 mb-6">
                    This page has wandered off the map. It may have been moved,
                    renamed, or never existed to begin with.
                </p>
                <div className="flex flex-col gap-3 sm:flex-row sm:justify-center">
                    <Link
                        to="/"
                        className="inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors font-medium"
                    >
                        <Home size={16} /> Back to Hub
                    </Link>
                    <Link
                        to="/models/discover"
                        className="inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg transition-colors font-medium text-gray-300"
                    >
                        <Search size={16} /> Discover Models
                    </Link>
                </div>
            </div>
        </div>
    );
}