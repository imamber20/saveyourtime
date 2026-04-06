import React from 'react';
import { motion } from 'framer-motion';
import { useAuth } from '../contexts/AuthContext';
import { User, Shield, Info } from 'lucide-react';

export default function SettingsPage() {
  const { user } = useAuth();

  return (
    <div data-testid="settings-page">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="font-heading text-2xl sm:text-3xl font-semibold text-text-primary mb-6">Settings</h1>

        <div className="space-y-4 max-w-2xl">
          {/* Profile */}
          <div className="bg-white border border-border-default rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-8 h-8 bg-brand/10 rounded-lg flex items-center justify-center">
                <User className="w-4 h-4 text-brand" />
              </div>
              <h2 className="font-heading font-semibold text-text-primary">Profile</h2>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs uppercase tracking-wider font-semibold text-text-secondary">Name</label>
                <p className="text-sm text-text-primary mt-0.5">{user?.name || 'N/A'}</p>
              </div>
              <div>
                <label className="text-xs uppercase tracking-wider font-semibold text-text-secondary">Email</label>
                <p className="text-sm text-text-primary mt-0.5">{user?.email || 'N/A'}</p>
              </div>
              <div>
                <label className="text-xs uppercase tracking-wider font-semibold text-text-secondary">Role</label>
                <p className="text-sm text-text-primary mt-0.5 capitalize">{user?.role || 'user'}</p>
              </div>
            </div>
          </div>

          {/* About */}
          <div className="bg-white border border-border-default rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-8 h-8 bg-sage/10 rounded-lg flex items-center justify-center">
                <Info className="w-4 h-4 text-sage" />
              </div>
              <h2 className="font-heading font-semibold text-text-primary">About</h2>
            </div>
            <p className="text-sm text-text-secondary leading-relaxed">
              Content Memory is a personal content organizer that helps you save and organize
              short-form social content from Instagram Reels, YouTube Shorts, and Facebook Reels.
              Save once, organize automatically, find instantly.
            </p>
            <div className="mt-4 pt-4 border-t border-border-default">
              <div className="flex items-center justify-between">
                <span className="text-xs text-text-secondary">Version</span>
                <span className="text-xs font-medium text-text-primary">1.0.0</span>
              </div>
            </div>
          </div>

          {/* Supported Platforms */}
          <div className="bg-white border border-border-default rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-8 h-8 bg-accent/10 rounded-lg flex items-center justify-center">
                <Shield className="w-4 h-4 text-accent" />
              </div>
              <h2 className="font-heading font-semibold text-text-primary">Supported Platforms</h2>
            </div>
            <div className="space-y-2">
              {['Instagram Reels', 'YouTube Shorts', 'Facebook Reels'].map(p => (
                <div key={p} className="flex items-center gap-2">
                  <div className="w-1.5 h-1.5 bg-green-500 rounded-full" />
                  <span className="text-sm text-text-primary">{p}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
