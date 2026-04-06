import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useAuth } from '../contexts/AuthContext';
import { formatApiErrorDetail } from '../services/api';
import { Bookmark, Eye, EyeOff } from 'lucide-react';

export default function RegisterPage() {
  const { register } = useAuth();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (password.length < 6) {
      setError('Password must be at least 6 characters');
      return;
    }
    setLoading(true);
    try {
      await register(email, password, name);
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-page flex items-center justify-center px-4" data-testid="register-page">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-md"
      >
        <div className="flex items-center justify-center gap-3 mb-10">
          <div className="w-10 h-10 bg-brand rounded-xl flex items-center justify-center">
            <Bookmark className="w-5 h-5 text-page" />
          </div>
          <span className="font-heading font-bold text-2xl text-text-primary tracking-tight">Content Memory</span>
        </div>

        <div className="bg-white border border-border-default rounded-2xl p-8 shadow-sm">
          <h1 className="font-heading text-2xl font-semibold text-text-primary mb-1">Create account</h1>
          <p className="text-text-secondary text-sm mb-6">Start saving your favorite content</p>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3 mb-4" data-testid="register-error">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-text-primary mb-1.5">Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                data-testid="register-name-input"
                className="w-full px-4 py-3 border border-border-default rounded-xl focus:border-brand focus:ring-2 focus:ring-brand/20 outline-none transition-all text-sm font-body"
                placeholder="Your name"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-primary mb-1.5">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                data-testid="register-email-input"
                className="w-full px-4 py-3 border border-border-default rounded-xl focus:border-brand focus:ring-2 focus:ring-brand/20 outline-none transition-all text-sm font-body"
                placeholder="you@example.com"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-primary mb-1.5">Password</label>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  data-testid="register-password-input"
                  className="w-full px-4 py-3 pr-12 border border-border-default rounded-xl focus:border-brand focus:ring-2 focus:ring-brand/20 outline-none transition-all text-sm font-body"
                  placeholder="Min. 6 characters"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPw(!showPw)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary"
                >
                  {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
            <button
              type="submit"
              disabled={loading}
              data-testid="register-submit-button"
              className="w-full bg-brand text-page rounded-full py-3.5 font-medium hover:bg-brand-hover transition-all duration-300 shadow-[0_2px_10px_rgba(195,107,88,0.2)] disabled:opacity-50"
            >
              {loading ? 'Creating account...' : 'Create Account'}
            </button>
          </form>
        </div>

        <p className="text-center text-sm text-text-secondary mt-6">
          Already have an account?{' '}
          <Link to="/login" className="text-brand hover:underline font-medium" data-testid="login-link">
            Sign in
          </Link>
        </p>
      </motion.div>
    </div>
  );
}
