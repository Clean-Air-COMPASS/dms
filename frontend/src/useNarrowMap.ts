import { useEffect, useState } from 'react';

/** Keep in sync with the existing Map and user-menu breakpoint in App.css. */
export function useNarrowMap() {
  const [narrow, setNarrow] = useState(() => window.matchMedia?.('(max-width: 768px)').matches ?? false);
  useEffect(() => {
    const query = window.matchMedia?.('(max-width: 768px)');
    if (!query) return;
    const update = () => setNarrow(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return narrow;
}

