import React from 'react';
import { Outlet, useMatch } from 'react-router-dom';
import Navbar from './Navbar';
import FloatingChat from './FloatingChat';

export default function Layout() {
  // Don't show the global library chat on item detail pages — that page
  // renders its own item-specific FloatingChat instead.
  const onItemPage = useMatch('/items/:id');

  return (
    <div className="min-h-screen bg-page" data-testid="app-layout">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 md:px-12 py-6 md:py-10">
        <Outlet />
      </main>

      {/* Global library chat — visible on all pages except individual item detail */}
      {!onItemPage && <FloatingChat mode="library" />}
    </div>
  );
}
