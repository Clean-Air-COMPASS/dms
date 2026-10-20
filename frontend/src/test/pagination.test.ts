import { describe, it, expect } from 'vitest';
import {
  calculateTotalPages,
  calculateDisplayRange,
  slicePage,
  clampPage,
  PAGE_SIZE_OPTIONS,
  DEFAULT_PAGE_SIZE,
} from '../utils/pagination';

describe('Pagination Utilities', () => {
  describe('calculateTotalPages', () => {
    it('returns 1 for empty data', () => {
      expect(calculateTotalPages(0, 25)).toBe(1);
    });

    it('returns 1 when items fit on one page', () => {
      expect(calculateTotalPages(10, 25)).toBe(1);
      expect(calculateTotalPages(25, 25)).toBe(1);
    });

    it('calculates correct pages for multiple pages', () => {
      expect(calculateTotalPages(26, 25)).toBe(2);
      expect(calculateTotalPages(50, 25)).toBe(2);
      expect(calculateTotalPages(51, 25)).toBe(3);
      expect(calculateTotalPages(100, 25)).toBe(4);
      expect(calculateTotalPages(101, 25)).toBe(5);
    });

    it('handles different page sizes', () => {
      expect(calculateTotalPages(100, 10)).toBe(10);
      expect(calculateTotalPages(100, 50)).toBe(2);
      expect(calculateTotalPages(100, 100)).toBe(1);
    });

    it('returns 1 for invalid inputs', () => {
      expect(calculateTotalPages(-1, 25)).toBe(1);
      expect(calculateTotalPages(100, 0)).toBe(1);
      expect(calculateTotalPages(100, -5)).toBe(1);
    });
  });

  describe('calculateDisplayRange', () => {
    it('returns zeros for empty data', () => {
      const result = calculateDisplayRange(1, 25, 0);
      expect(result).toEqual({ start: 0, end: 0, total: 0 });
    });

    it('calculates correct range for first page', () => {
      expect(calculateDisplayRange(1, 25, 100)).toEqual({ start: 1, end: 25, total: 100 });
      expect(calculateDisplayRange(1, 10, 50)).toEqual({ start: 1, end: 10, total: 50 });
    });

    it('calculates correct range for middle pages', () => {
      expect(calculateDisplayRange(2, 25, 100)).toEqual({ start: 26, end: 50, total: 100 });
      expect(calculateDisplayRange(3, 25, 100)).toEqual({ start: 51, end: 75, total: 100 });
    });

    it('calculates correct range for last page (partial)', () => {
      expect(calculateDisplayRange(4, 25, 100)).toEqual({ start: 76, end: 100, total: 100 });
      expect(calculateDisplayRange(5, 25, 101)).toEqual({ start: 101, end: 101, total: 101 });
    });

    it('handles small datasets', () => {
      expect(calculateDisplayRange(1, 25, 5)).toEqual({ start: 1, end: 5, total: 5 });
      expect(calculateDisplayRange(1, 25, 1)).toEqual({ start: 1, end: 1, total: 1 });
    });

    it('handles edge case where items equal page size exactly', () => {
      expect(calculateDisplayRange(1, 25, 25)).toEqual({ start: 1, end: 25, total: 25 });
      expect(calculateDisplayRange(2, 25, 50)).toEqual({ start: 26, end: 50, total: 50 });
    });
  });

  describe('slicePage', () => {
    const items = Array.from({ length: 100 }, (_, i) => i + 1);

    it('returns empty array for empty input', () => {
      expect(slicePage([], 1, 25)).toEqual([]);
    });

    it('returns first page items', () => {
      const result = slicePage(items, 1, 25);
      expect(result).toHaveLength(25);
      expect(result[0]).toBe(1);
      expect(result[24]).toBe(25);
    });

    it('returns second page items', () => {
      const result = slicePage(items, 2, 25);
      expect(result).toHaveLength(25);
      expect(result[0]).toBe(26);
      expect(result[24]).toBe(50);
    });

    it('returns partial last page', () => {
      const smallItems = Array.from({ length: 30 }, (_, i) => i + 1);
      const result = slicePage(smallItems, 2, 25);
      expect(result).toHaveLength(5);
      expect(result[0]).toBe(26);
      expect(result[4]).toBe(30);
    });

    it('returns all items when page size exceeds total', () => {
      const smallItems = [1, 2, 3];
      expect(slicePage(smallItems, 1, 25)).toEqual([1, 2, 3]);
    });

    it('works with different page sizes', () => {
      expect(slicePage(items, 1, 10)).toHaveLength(10);
      expect(slicePage(items, 1, 50)).toHaveLength(50);
      expect(slicePage(items, 2, 50)).toHaveLength(50);
      expect(slicePage(items, 3, 50)).toHaveLength(0);
    });

    it('handles objects correctly', () => {
      const objItems = [{ id: 1 }, { id: 2 }, { id: 3 }];
      const result = slicePage(objItems, 1, 2);
      expect(result).toEqual([{ id: 1 }, { id: 2 }]);
    });
  });

  describe('clampPage', () => {
    it('returns page if within valid range', () => {
      expect(clampPage(1, 5)).toBe(1);
      expect(clampPage(3, 5)).toBe(3);
      expect(clampPage(5, 5)).toBe(5);
    });

    it('clamps to 1 if page is below 1', () => {
      expect(clampPage(0, 5)).toBe(1);
      expect(clampPage(-1, 5)).toBe(1);
      expect(clampPage(-100, 5)).toBe(1);
    });

    it('clamps to totalPages if page exceeds total', () => {
      expect(clampPage(6, 5)).toBe(5);
      expect(clampPage(100, 5)).toBe(5);
    });

    it('handles edge case of 1 total page', () => {
      expect(clampPage(0, 1)).toBe(1);
      expect(clampPage(1, 1)).toBe(1);
      expect(clampPage(2, 1)).toBe(1);
    });
  });

  describe('Constants', () => {
    it('PAGE_SIZE_OPTIONS contains expected values', () => {
      expect(PAGE_SIZE_OPTIONS).toEqual([10, 25, 50, 100]);
    });

    it('DEFAULT_PAGE_SIZE is 25', () => {
      expect(DEFAULT_PAGE_SIZE).toBe(25);
    });

    it('DEFAULT_PAGE_SIZE is in PAGE_SIZE_OPTIONS', () => {
      expect(PAGE_SIZE_OPTIONS).toContain(DEFAULT_PAGE_SIZE);
    });
  });
});
