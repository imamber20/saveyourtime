import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { collectionsAPI } from '../services/api';
import EmptyState from '../components/EmptyState';
import {
  Plus, Trash2, Loader2,
  Dumbbell, Plane, ChefHat, Cpu, GraduationCap,
  Clapperboard, TrendingUp, ShoppingBag, FolderOpen,
  Leaf, Music2, Gamepad2, Palette, Heart, Baby,
  Newspaper, Home
} from 'lucide-react';

// ── Category → icon + accent colour ──────────────────────────────────────────
const COLLECTION_STYLE = {
  'Fitness & Health':  { Icon: Dumbbell,     bg: 'bg-emerald-50',  iconColor: 'text-emerald-600' },
  'Travel':            { Icon: Plane,         bg: 'bg-sky-50',      iconColor: 'text-sky-600' },
  'Food & Recipes':    { Icon: ChefHat,       bg: 'bg-orange-50',   iconColor: 'text-orange-500' },
  'Technology':        { Icon: Cpu,           bg: 'bg-violet-50',   iconColor: 'text-violet-600' },
  'Learning':          { Icon: GraduationCap, bg: 'bg-yellow-50',   iconColor: 'text-yellow-600' },
  'Entertainment':     { Icon: Clapperboard,  bg: 'bg-pink-50',     iconColor: 'text-pink-500' },
  'Finance':           { Icon: TrendingUp,    bg: 'bg-teal-50',     iconColor: 'text-teal-600' },
  'Fashion & Style':   { Icon: ShoppingBag,   bg: 'bg-rose-50',     iconColor: 'text-rose-500' },
  'Nature & Outdoors': { Icon: Leaf,          bg: 'bg-green-50',    iconColor: 'text-green-600' },
  'Music':             { Icon: Music2,        bg: 'bg-fuchsia-50',  iconColor: 'text-fuchsia-600' },
  'Gaming':            { Icon: Gamepad2,      bg: 'bg-indigo-50',   iconColor: 'text-indigo-600' },
  'Art & Creativity':  { Icon: Palette,       bg: 'bg-amber-50',    iconColor: 'text-amber-600' },
  'Relationships':     { Icon: Heart,         bg: 'bg-red-50',      iconColor: 'text-red-500' },
  'Parenting':         { Icon: Baby,          bg: 'bg-lime-50',     iconColor: 'text-lime-600' },
  'News':              { Icon: Newspaper,     bg: 'bg-slate-50',    iconColor: 'text-slate-600' },
  'Home & Interior':   { Icon: Home,          bg: 'bg-stone-50',    iconColor: 'text-stone-600' },
};

function getCollectionStyle(name) {
  // exact match first
  if (COLLECTION_STYLE[name]) return COLLECTION_STYLE[name];
  // partial match
  for (const [key, val] of Object.entries(COLLECTION_STYLE)) {
    if (name.toLowerCase().includes(key.toLowerCase()) ||
        key.toLowerCase().includes(name.toLowerCase())) {
      return val;
    }
  }
  return { Icon: FolderOpen, bg: 'bg-sage/10', iconColor: 'text-sage' };
}

export default function CollectionsPage() {
  const navigate = useNavigate();
  const [collections, setCollections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => { fetchCollections(); }, []);

  const fetchCollections = async () => {
    try {
      const { data } = await collectionsAPI.list();
      setCollections(data.collections || []);
    } catch (err) {
      console.error('Failed to fetch collections:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await collectionsAPI.create({ name: newName, description: newDesc });
      setNewName(''); setNewDesc(''); setShowCreate(false);
      fetchCollections();
    } catch {} finally { setCreating(false); }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this collection?')) return;
    try { await collectionsAPI.delete(id); fetchCollections(); } catch {}
  };

  return (
    <div data-testid="collections-page">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <div className="flex items-center justify-between mb-6">
          <h1 className="font-heading text-2xl sm:text-3xl font-semibold text-text-primary">Collections</h1>
          <button
            onClick={() => setShowCreate(!showCreate)}
            data-testid="create-collection-button"
            className="flex items-center gap-2 bg-brand text-page rounded-full px-5 py-2.5 text-sm font-medium hover:bg-brand-hover transition-all shadow-[0_2px_10px_rgba(195,107,88,0.2)]"
          >
            <Plus className="w-4 h-4" /> New Collection
          </button>
        </div>

        {showCreate && (
          <motion.form
            initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
            onSubmit={handleCreate}
            className="bg-white border border-border-default rounded-2xl p-6 mb-6 shadow-sm"
            data-testid="create-collection-form"
          >
            <div className="space-y-3">
              <input value={newName} onChange={(e) => setNewName(e.target.value)}
                placeholder="Collection name" data-testid="collection-name-input" autoFocus
                className="w-full px-4 py-2.5 border border-border-default rounded-xl text-sm focus:border-brand outline-none" />
              <input value={newDesc} onChange={(e) => setNewDesc(e.target.value)}
                placeholder="Description (optional)" data-testid="collection-desc-input"
                className="w-full px-4 py-2.5 border border-border-default rounded-xl text-sm focus:border-brand outline-none" />
              <div className="flex gap-2">
                <button type="submit" disabled={creating} data-testid="save-collection-button"
                  className="bg-brand text-page rounded-full px-5 py-2 text-sm font-medium hover:bg-brand-hover transition-colors disabled:opacity-50">
                  {creating ? 'Creating...' : 'Create'}
                </button>
                <button type="button" onClick={() => setShowCreate(false)}
                  className="border border-border-default rounded-full px-5 py-2 text-sm hover:bg-surface-hover transition-colors">
                  Cancel
                </button>
              </div>
            </div>
          </motion.form>
        )}
      </motion.div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 text-brand animate-spin" />
        </div>
      ) : collections.length === 0 ? (
        <EmptyState
          title="No collections yet"
          message="Create a collection to organise your saved content."
          actionLabel="Create Collection"
          onAction={() => setShowCreate(true)}
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 md:gap-6" data-testid="collections-grid">
          {collections.map((coll, i) => {
            const { Icon, bg, iconColor } = getCollectionStyle(coll.name);
            return (
              <motion.div
                key={coll.id}
                initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                onClick={() => navigate(`/collections/${coll.id}`)}
                className="bg-white border border-border-default rounded-2xl p-6 cursor-pointer group transition-all duration-300 hover:-translate-y-1 hover:border-sage hover:shadow-md"
                data-testid={`collection-card-${coll.id}`}
              >
                <div className="flex items-start justify-between">
                  <div className={`w-11 h-11 ${bg} rounded-xl flex items-center justify-center mb-4`}>
                    <Icon className={`w-5 h-5 ${iconColor}`} />
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDelete(coll.id); }}
                    className="p-1.5 rounded-lg opacity-0 group-hover:opacity-100 hover:bg-red-50 transition-all"
                    aria-label="Delete collection"
                  >
                    <Trash2 className="w-3.5 h-3.5 text-red-400" />
                  </button>
                </div>
                <h3 className="font-heading font-semibold text-text-primary mb-1">{coll.name}</h3>
                {coll.description && (
                  <p className="text-sm text-text-secondary mb-2 line-clamp-2">{coll.description}</p>
                )}
                <span className="text-xs text-text-secondary">{coll.item_count || 0} items</span>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}
