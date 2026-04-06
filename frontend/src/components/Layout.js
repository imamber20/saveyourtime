import React from 'react';
import { Outlet } from 'react-router-dom';
import Navbar from './Navbar';

export default function Layout() {
  return (
    <div className="min-h-screen bg-page" data-testid="app-layout">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 md:px-12 py-6 md:py-10">
        <Outlet />
      </main>
    </div>
  );
}
