import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { authAPI, formatApiErrorDetail } from '../services/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null = checking, false = not auth'd
  const [loading, setLoading] = useState(true);

  const checkAuth = useCallback(async () => {
    try {
      const { data } = await authAPI.me();
      setUser(data);
    } catch {
      setUser(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const login = async (email, password) => {
    const { data } = await authAPI.login({ email, password });
    setUser(data);
    return data;
  };

  const register = async (email, password, name) => {
    const { data } = await authAPI.register({ email, password, name });
    setUser(data);
    return data;
  };

  const logout = async () => {
    try {
      await authAPI.logout();
    } catch {}
    setUser(false);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, checkAuth }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
