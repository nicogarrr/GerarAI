import { render } from '@testing-library/react';
import { expect, it } from 'vitest';
import { MaterialsLineSkeleton } from '@/components/calendar/FollowedEarningsList';
it('renders a hidden noninteractive space reservation', () => {
  const { container } = render(<MaterialsLineSkeleton />);
  expect(container.querySelector('p')?.getAttribute('aria-hidden')).toBe('true');
  expect(container.querySelector('.h-6')).not.toBeNull();
  expect(container.querySelectorAll('a,button,input')).toHaveLength(0);
});
