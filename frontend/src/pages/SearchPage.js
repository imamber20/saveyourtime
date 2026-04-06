import React, { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import { searchAPI, categoriesAPI } from '../services/api';
import ItemCard from '../components/ItemCard';
import EmptyState from '../components/EmptyState';
import { Search as SearchIcon, Filter, Loader2, X } from 'lucide-react';

export default function SearchPage() {
  const [query, setQuery] = useState('');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [category, setCategory] = useState('');
  const [platform, setPlatform] = useState('');
  const [tag, setTag] = useState('');
  const [categories, setCategories] = useState([]);
  const [catLoaded, setCatLoaded] = useState(false);

  const loadCategories = useCallback(async () => {
    if (catLoaded) return;
    try {
      const { data } = await categoriesAPI.list();
      setCategories(data.categories || []);
      setCatLoaded(true);
    } catch {}
  }, [catLoaded]);

  const handleSearch = async (e) => {
    e?.preventDefault();
    setLoading(true);
    setSearched(true);
    try {
      const params = {};
      if (query.trim()) params.q = query.trim();
      if (category) params.category = category;
      if (platform) params.platform = platform;
      if (tag) params.tag = tag;
      const { data } = await searchAPI.search(params);
      setItems(data.items || []);
    } catch (err) {
      console.error('Search failed:', err);
    } finally {
      setLoading(false);
    }
  };

  const clearFilters = () => {
    setCategory('');
    setPlatform('');
    setTag('');
    setQuery('');
    setSearched(false);
    setItems([]);
  };

  return (
    <div data-testid="search-page">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="font-heading text-2xl sm:text-3xl font-semibold text-text-primary mb-6">Search</h1>

        {/* Search Form */}
        <form onSubmit={handleSearch} className="mb-6" data-testid="search-form">
          <div className="relative max-w-2xl">
            <SearchIcon className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-text-secondary" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onFocus={loadCategories}
              placeholder="Search your saved content..."
              data-testid="search-input"
              className="w-full pl-12 pr-12 py-3.5 bg-white border border-border-default rounded-full text-sm focus:border-brand outline-none transition-all shadow-sm"
            />
            {query && (
              <button type="button" onClick={() => setQuery('')}
                className="absolute right-4 top-1/2 -translate-y-1/2 text-text-secondary hover:text-text-primary">
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        </form>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2 mb-6" data-testid="search-filters">
          <Filter className="w-4 h-4 text-text-secondary" />
          <select value={platform} onChange={(e) => setPlatform(e.target.value)} data-testid="search-filter-platform"
            className="px-3 py-1.5 rounded-full text-xs border border-border-default bg-white text-text-secondary focus:border-brand outline-none">
            <option value="">All Platforms</option>
            <option value="instagram">Instagram</option>
            <option value="youtube">YouTube</option>
            <option value="facebook">Facebook</option>
          </select>
          <select value={category} onChange={(e) => setCategory(e.target.value)} data-testid="search-filter-category"
            onFocus={loadCategories}
            className="px-3 py-1.5 rounded-full text-xs border border-border-default bg-white text-text-secondary focus:border-brand outline-none">
            <option value="">All Categories</option>
            {categories.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
          <input
            value={tag}
            onChange={(e) => setTag(e.target.value)}
            placeholder="Filter by tag..."
            data-testid="search-filter-tag"
            className="px-3 py-1.5 rounded-full text-xs border border-border-default bg-white text-text-secondary focus:border-brand outline-none w-32"
          />
          <button onClick={handleSearch} data-testid="search-submit-button"
            className="bg-brand text-page rounded-full px-5 py-1.5 text-xs font-medium hover:bg-brand-hover transition-colors">
            Search
          </button>
          {(category || platform || tag || query) && (
            <button onClick={clearFilters} className="text-xs text-text-secondary hover:text-brand underline">
              Clear all
            </button>
          )}
        </div>
      </motion.div>

      {/* Results */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 text-brand animate-spin" />
        </div>
      ) : searched && items.length === 0 ? (
        <EmptyState title="No results found" message="Try adjusting your search terms or filters." />
      ) : items.length > 0 ? (
        <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 md:gap-6" data-testid="search-results-grid">
          {items.map((item, i) => <ItemCard key={item.id} item={item} index={i} />)}
        </div>
      ) : !searched ? (
        <div className="text-center py-16">
          <p className="text-text-secondary">Start typing to search your saved content</p>
        </div>
      ) : null}
    </div>
  );
}
