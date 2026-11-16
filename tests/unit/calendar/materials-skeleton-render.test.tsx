import { renderToString } from 'react-dom/server';
import { render } from '@testing-library/react';
import { expect, it } from 'vitest';
import { MaterialsLineSkeleton } from '@/components/calendar/FollowedEarningsList';
it('renders a hidden noninteractive space reservation', () => {
  const { container } = render(<MaterialsLineSkeleton />);
  expect(container.querySelector('div[aria-hidden]')?.getAttribute('aria-hidden')).toBe('true');
  expect(container.querySelector('.h-6')).not.toBeNull();
  expect(container.querySelectorAll('a,button,input')).toHaveLength(0);
});

it('keeps the reserved height inside aria-hidden after SSR HTML parsing', () => {
  const markup = renderToString(<MaterialsLineSkeleton />);
  const parsed = new DOMParser().parseFromString(markup, 'text/html');
  const reserved = parsed.querySelector('.h-6');
  expect(reserved).not.toBeNull();
  expect(reserved?.closest('[aria-hidden="true"]')).not.toBeNull();
  expect(parsed.querySelector('p')).toBeNull();
});
