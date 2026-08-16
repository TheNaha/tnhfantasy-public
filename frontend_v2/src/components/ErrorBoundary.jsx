import React from 'react';
import { AlertTriangle } from 'lucide-react';

class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, errorInfo) {
        console.error('ErrorBoundary caught an error:', error, errorInfo);
    }

    reset = () => {
        this.setState({ hasError: false, error: null });
    };

    render() {
        if (this.state.hasError) {
            return (
                <div className="flex flex-col items-center justify-center min-h-screen bg-gray-900 text-white p-6">
                    <div className="glass rounded-lg p-8 max-w-lg text-center">
                        <AlertTriangle className="mx-auto mb-4 text-red-500" size={64} />
                        <h1 className="text-2xl font-bold mb-4">Oops! Something went wrong</h1>
                        <p className="text-gray-400 mb-6">
                            The application encountered an unexpected error.
                        </p>
                        {this.state.error && import.meta.env.DEV && (
                            <details className="text-left text-sm bg-gray-800 p-4 rounded mb-4">
                                <summary className="cursor-pointer font-semibold mb-2">Error Details (Dev Only)</summary>
                                <pre className="text-red-400 whitespace-pre-wrap">
                                    {this.state.error.toString()}
                                </pre>
                            </details>
                        )}
                        <div className="flex justify-center gap-3">
                            <button
                                onClick={this.reset}
                                className="px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
                            >
                                Try again
                            </button>
                            <button
                                onClick={() => window.location.reload()}
                                className="px-6 py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg transition-colors"
                            >
                                Refresh Page
                            </button>
                        </div>
                    </div>
                </div>
            );
        }

        return this.props.children;
    }
}

export default ErrorBoundary;
