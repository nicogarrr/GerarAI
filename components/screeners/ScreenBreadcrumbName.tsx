'use client';
import { useEffect } from 'react';
export function ScreenBreadcrumbName({ name }: { name: string }) {
  useEffect(() => {
    const timer = window.setTimeout(() => window.dispatchEvent(new CustomEvent('page-breadcrumb-name', { detail: { path: window.location.pathname, name } })), 0);
    return () => window.clearTimeout(timer);
  }, [name]);
  return null;
}
