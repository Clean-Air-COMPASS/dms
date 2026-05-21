


export function calculateTotalPages(totalItems: number, pageSize: number): number {
  if (totalItems <= 0 || pageSize <= 0) return 1;
  return Math.ceil(totalItems / pageSize);
}


export function calculateDisplayRange(
  currentPage: number,
  pageSize: number,
  totalItems: number
): { start: number; end: number; total: number } {
  if (totalItems <= 0) return { start: 0, end: 0, total: 0 };
  const start = (currentPage - 1) * pageSize + 1;
  const end = Math.min(currentPage * pageSize, totalItems);
  return { start, end, total: totalItems };
}


export function slicePage<T>(items: T[], currentPage: number, pageSize: number): T[] {
  if (!items || items.length === 0) return [];
  const startIndex = (currentPage - 1) * pageSize;
  return items.slice(startIndex, startIndex + pageSize);
}


export function clampPage(page: number, totalPages: number): number {
  return Math.max(1, Math.min(page, totalPages));
}


export const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;
export type PageSize = typeof PAGE_SIZE_OPTIONS[number];


export const DEFAULT_PAGE_SIZE: PageSize = 25;
