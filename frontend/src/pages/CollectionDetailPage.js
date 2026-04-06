import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { collectionsAPI } from '../services/api';
import ItemCard from '../components/ItemCard';
import EmptyState from '../components/EmptyState';
import { ArrowLeft, Edit3, Loader2 } from 'lucide-react';

export default function CollectionDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [collection, setCollection] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchCollection();
  }, [id]);

  const fetchCollection = async () => {
    try {
      const { data } = await collectionsAPI.get(id);
      setCollection(data);
    } catch {
      navigate('/collections');
    } finally {
      setLoading(false);
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <Loader2 className="w-8 h-8 text-brand animate-spin" />
    </div>
  );

  if (!collection) return null;

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} data-testid="collection-detail-page">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/collections')} data-testid="back-to-collections"
            className="p-2 rounded-full hover:bg-surface-hover transition-colors">
            <ArrowLeft className="w-4 h-4 text-text-secondary" />
          </button>
          <div>
            <h1 className="font-heading text-xl sm:text-2xl font-semibold text-text-primary">{collection.name}</h1>
            {collection.description && (
              <p className="text-sm text-text-secondary">{collection.description}</p>
            )}
          </div>
        </div>
        <span className="text-sm text-text-secondary">{collection.item_count || 0} items</span>
      </div>

      {(!collection.items || collection.items.length === 0) ? (
        <EmptyState
          title="This collection is empty"
          message="Add items to this collection from the item detail page."
          actionLabel="Browse Items"
          onAction={() => navigate('/')}
        />
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 md:gap-6" data-testid="collection-items-grid">
          {collection.items.map((item, i) => (
            <ItemCard key={item.id} item={item} index={i} />
          ))}
        </div>
      )}
    </motion.div>
  );
}
