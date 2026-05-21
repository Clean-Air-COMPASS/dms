

import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useAuth } from './auth';
import PasswordInput from './components/PasswordInput';

interface LocationState {
  from?: { pathname: string };
}

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, isAuthenticated, isLoading: authLoading } = useAuth();

  
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  
  const locationState = location.state as LocationState | null;
  const from = locationState?.from?.pathname || '/map';

  
  useEffect(() => {
    if (isAuthenticated && !authLoading) {
      navigate(from, { replace: true });
    }
  }, [isAuthenticated, authLoading, navigate, from]);

  
  function sanitizeAuthError(_error: string | undefined, statusCode?: number): string {
    
    if (statusCode === 429) {
      return 'Too many sign-in attempts. Please try again later.';
    }

    
    
    return 'Invalid email or password.';
  }

  
  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    
    const trimmedEmail = email.trim();
    const trimmedPassword = password.trim();

    if (!trimmedEmail) {
      setError('Please enter your email address');
      return;
    }

    if (!trimmedPassword) {
      setError('Please enter your password');
      return;
    }

    
    setIsSubmitting(true);
    const result = await login({ email: trimmedEmail, password: trimmedPassword });
    setIsSubmitting(false);

    if (result.success) {
      
      
      try {
        
        const credApi = (navigator as any).credentials;
        const PwCred = (window as any).PasswordCredential;
        if (credApi && typeof credApi.store === 'function' && PwCred) {
          try {
            const cred = new PwCred({ id: trimmedEmail, password: trimmedPassword });
            
            await credApi.store(cred);
          } catch {
            // ignore failures — this API is optional
          }
        }
      } catch {
        // silent
      }
      
      navigate(from, { replace: true });
    } else {
      
      
      const sanitizedError = sanitizeAuthError(result.error, result.statusCode);
      setError(sanitizedError);
    }
  }

  
  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-slate-600">Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md">
        
        <div className="text-center mb-8">
          <Link to="/" className="inline-block">
            <h1 className="text-3xl font-bold text-slate-800 tracking-tight">COMPASS</h1>
          </Link>
          <p className="text-slate-600 mt-2">Air Quality Data Platform</p>
        </div>

        
        <div className="bg-white shadow-lg rounded-lg border border-slate-200 p-8">
          <h2 className="text-xl font-semibold text-slate-800 mb-6">Sign In</h2>

          
          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md text-red-700 text-sm">
              {error}
            </div>
          )}

          
          <form onSubmit={handleSubmit} className="space-y-4">
            
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-1">
                Email
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={isSubmitting}
                name="username"
                autoComplete="username"
                autoFocus
                className="w-full px-3 py-2 border border-slate-300 rounded-md shadow-sm 
                         focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
                         disabled:bg-slate-100 disabled:cursor-not-allowed"
                placeholder="you@example.com"
              />
            </div>

            
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-slate-700 mb-1">
                Password
              </label>
              <PasswordInput
                id="password"
                name="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isSubmitting}
                autoComplete="current-password"
                className="w-full px-3 py-2 border border-slate-300 rounded-md shadow-sm 
                         focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
                         disabled:bg-slate-100 disabled:cursor-not-allowed"
                placeholder="••••••••"
              />
            </div>

            
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-2 px-4 bg-blue-600 font-medium rounded-md
                       hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
                       disabled:bg-blue-400 disabled:cursor-not-allowed
                       transition-colors duration-200"
            >
              {isSubmitting ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></span>
                  Signing in...
                </span>
              ) : (
                'Sign In'
              )}
            </button>
          </form>
        </div>

        
        <div className="text-center mt-6">
          <Link to="/" className="text-sm text-slate-600 hover:text-blue-600">
            ← Back to Home
          </Link>
        </div>
      </div>
    </div>
  );
}
