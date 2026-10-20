import { describe, it, expect, vi, beforeEach } from 'vitest';
import { copyToClipboard, formatCoordinates } from '../utils/clipboard';

describe('clipboard utilities', () => {
  describe('formatCoordinates', () => {
    it('should format valid coordinates with default precision', () => {
      expect(formatCoordinates(37.7749, -122.4194)).toBe('37.7749, -122.4194');
    });

    it('should format coordinates with custom precision', () => {
      expect(formatCoordinates(37.77493, -122.41942, 2)).toBe('37.77, -122.42');
      expect(formatCoordinates(37.77493, -122.41942, 6)).toBe('37.774930, -122.419420');
    });

    it('should return em dash for null latitude', () => {
      expect(formatCoordinates(null, -122.4194)).toBe('—');
    });

    it('should return em dash for null longitude', () => {
      expect(formatCoordinates(37.7749, null)).toBe('—');
    });

    it('should return em dash for undefined values', () => {
      expect(formatCoordinates(undefined, undefined)).toBe('—');
    });

    it('should return em dash for non-finite values', () => {
      expect(formatCoordinates(NaN, -122.4194)).toBe('—');
      expect(formatCoordinates(37.7749, Infinity)).toBe('—');
    });

    it('should handle zero values correctly', () => {
      expect(formatCoordinates(0, 0)).toBe('0.0000, 0.0000');
    });

    it('should handle negative coordinates', () => {
      expect(formatCoordinates(-33.8688, 151.2093)).toBe('-33.8688, 151.2093');
    });
  });

  describe('copyToClipboard', () => {
    beforeEach(() => {
      vi.restoreAllMocks();
    });

    it('should return false for empty text', async () => {
      const result = await copyToClipboard('');
      expect(result).toBe(false);
    });

    it('should use navigator.clipboard.writeText when available', async () => {
      const mockWriteText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: mockWriteText },
        writable: true,
        configurable: true,
      });

      const result = await copyToClipboard('test text');

      expect(result).toBe(true);
      expect(mockWriteText).toHaveBeenCalledWith('test text');
    });

    it('should return true on successful clipboard write', async () => {
      const mockWriteText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: mockWriteText },
        writable: true,
        configurable: true,
      });

      const result = await copyToClipboard('37.7749, -122.4194');
      expect(result).toBe(true);
    });

    it('should return false when clipboard API fails', async () => {
      const mockWriteText = vi.fn().mockRejectedValue(new Error('Failed'));
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: mockWriteText },
        writable: true,
        configurable: true,
      });

      const result = await copyToClipboard('test text');
      expect(result).toBe(false);
    });

    it('should handle missing clipboard API', async () => {
      
      Object.defineProperty(navigator, 'clipboard', {
        value: undefined,
        writable: true,
        configurable: true,
      });

      
      const mockExecCommand = vi.fn().mockReturnValue(true);
      document.execCommand = mockExecCommand;

      const result = await copyToClipboard('test text');
      expect(result).toBe(true);
    });
  });
});
