'use client';
import { useEffect } from 'react';
export function ScreenBreadcrumbName({ name }: { name: string }) {
  useEffect(() => {
    document.documentElement.dataset.pageBreadcrumb = JSON.stringify({path:window.location.pathname,name});
    const timer = window.setTimeout(() => window.dispatchEvent(new CustomEvent('page-breadcrumb-name', { detail: { path: window.location.pathname, name } })), 0);
    return () => { window.clearTimeout(timer); delete document.documentElement.dataset.pageBreadcrumb; };
  }, [name]);
  return null;
}
