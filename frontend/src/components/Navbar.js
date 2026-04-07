import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Home, Search, FolderOpen, MapPin, Settings, LogOut, Menu, X, Bookmark, TrendingUp } from 'lucide-react';

const NAV_ITEMS = [
  { path: '/', label: 'Home', icon: Home },
  { path: '/search', label: 'Search', icon: Search },
  { path: '/collections', label: 'Collections', icon: FolderOpen },
  { path: '/map', label: 'Map', icon: MapPin },
  { path: '/trending', label: 'Trending', icon: TrendingUp },
  { path: '/settings', label: 'Settings', icon: Settings },
];

export default function Navbar() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <header className="bg-page/80 backdrop-blur-xl border-b border-border-default sticky top-0 z-50" data-testid="navbar">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 md:px-12">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-2.5 group" data-testid="nav-logo">
            <div className="w-8 h-8 bg-brand rounded-lg flex items-center justify-center">
              <Bookmark className="w-4 h-4 text-page" />
            </div>
            <span className="font-heading font-semibold text-lg text-text-primary tracking-tight">
              Content Memory
            </span>
          </Link>

          {/* Desktop Nav */}
          <nav className="hidden md:flex items-center gap-1" data-testid="desktop-nav">
            {NAV_ITEMS.map(({ path, label, icon: Icon }) => {
              const active = location.pathname === path || (path !== '/' && location.pathname.startsWith(path));
              return (
                <Link
                  key={path}
                  to={path}
                  data-testid={`nav-${label.toLowerCase()}`}
                  className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-all duration-200
                    ${active
                      ? 'bg-brand/10 text-brand'
                      : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'
                    }`}
                >
                  <Icon className="w-4 h-4" />
                  {label}
                </Link>
              );
            })}
          </nav>

          {/* User + Mobile Toggle */}
          <div className="flex items-center gap-3">
            {user && (
              <span className="hidden sm:block text-sm text-text-secondary">{user.name || user.email}</span>
            )}
            <button
              onClick={logout}
              data-testid="logout-button"
              className="hidden md:flex items-center gap-2 px-3 py-2 rounded-full text-sm text-text-secondary hover:text-brand hover:bg-surface-hover transition-colors"
              aria-label="Logout"
            >
              <LogOut className="w-4 h-4" />
            </button>
            <button
              onClick={() => setMobileOpen(!mobileOpen)}
              className="md:hidden p-2 rounded-lg hover:bg-surface-hover"
              data-testid="mobile-menu-toggle"
              aria-label="Toggle menu"
            >
              {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          </div>
        </div>

        {/* Mobile Nav */}
        {mobileOpen && (
          <nav className="md:hidden pb-4 border-t border-border-default pt-3 space-y-1" data-testid="mobile-nav">
            {NAV_ITEMS.map(({ path, label, icon: Icon }) => {
              const active = location.pathname === path;
              return (
                <Link
                  key={path}
                  to={path}
                  onClick={() => setMobileOpen(false)}
                  className={`flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm font-medium transition-colors
                    ${active ? 'bg-brand/10 text-brand' : 'text-text-secondary hover:bg-surface-hover'}`}
                >
                  <Icon className="w-4 h-4" />
                  {label}
                </Link>
              );
            })}
            <button
              onClick={() => { logout(); setMobileOpen(false); }}
              className="flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm font-medium text-text-secondary hover:text-brand w-full"
            >
              <LogOut className="w-4 h-4" />
              Logout
            </button>
          </nav>
        )}
      </div>

    </header>
  );
}
