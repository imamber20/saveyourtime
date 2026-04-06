import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { collectionsAPI } from '../services/api';
import EmptyState from '../components/EmptyState';
import { FolderOpen, Plus, Trash2, Edit3, Loader2 } from 'lucide-react';

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
      setNewName('');
      setNewDesc('');
      setShowCreate(false);
      fetchCollections();
    } catch {} finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this collection?')) return;
    try {
      await collectionsAPI.delete(id);
      fetchCollections();
    } catch {}
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
            <Plus className="w-4 h-4" />
            New Collection
          </button>
        </div>

        {/* Create Form */}
        {showCreate && (
          <motion.form
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            onSubmit={handleCreate}
            className="bg-white border border-border-default rounded-2xl p-6 mb-6 shadow-sm"
            data-testid="create-collection-form"
          >
            <div className="space-y-3">
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Collection name"
                data-testid="collection-name-input"
                className="w-full px-4 py-2.5 border border-border-default rounded-xl text-sm focus:border-brand outline-none"
                autoFocus
              />
              <input
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                placeholder="Description (optional)"
                data-testid="collection-desc-input"
                className="w-full px-4 py-2.5 border border-border-default rounded-xl text-sm focus:border-brand outline-none"
              />
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

      {/* Collections List */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 text-brand animate-spin" />
        </div>
      ) : collections.length === 0 ? (
        <EmptyState
          title="No collections yet"
          message="Create a collection to organize your saved content into boards."
          actionLabel="Create Collection"
          onAction={() => setShowCreate(true)}
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 md:gap-6" data-testid="collections-grid">
          {collections.map((coll, i) => (
            <motion.div
              key={coll.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              onClick={() => navigate(`/collections/${coll.id}`)}
              className="bg-white border border-border-default rounded-2xl p-6 cursor-pointer group transition-all duration-300 hover:-translate-y-1 hover:border-sage hover:shadow-md"
              data-testid={`collection-card-${coll.id}`}
            >
              <div className="flex items-start justify-between">
                <div className="w-10 h-10 bg-sage/10 rounded-xl flex items-center justify-center mb-4">
                  <FolderOpen className="w-5 h-5 text-sage" />
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
          ))}
        </div>
      )}
    </div>
  );
}
