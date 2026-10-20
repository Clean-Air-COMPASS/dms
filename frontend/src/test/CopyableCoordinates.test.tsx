import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import CopyableCoordinates from '../components/CopyableCoordinates';


vi.mock('../utils/clipboard', () => ({
  copyToClipboard: vi.fn(),
  formatCoordinates: vi.fn((lat, lon, precision = 4) => {
    if (lat == null || lon == null) return '—';
    return `${lat.toFixed(precision)}, ${lon.toFixed(precision)}`;
  }),
}));

import { copyToClipboard } from '../utils/clipboard';

describe('CopyableCoordinates', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (copyToClipboard as ReturnType<typeof vi.fn>).mockResolvedValue(true);
  });

  describe('rendering', () => {
    it('should render coordinates with default precision', () => {
      render(<CopyableCoordinates latitude={37.7749} longitude={-122.4194} />);
      expect(screen.getByText('37.7749, -122.4194')).toBeInTheDocument();
    });

    it('should render em dash for null coordinates', () => {
      render(<CopyableCoordinates latitude={null} longitude={null} />);
      expect(screen.getByText('—')).toBeInTheDocument();
    });

    it('should apply custom className', () => {
      render(
        <CopyableCoordinates 
          latitude={37.7749} 
          longitude={-122.4194} 
          className="custom-class"
        />
      );
      const element = screen.getByRole('button');
      expect(element).toHaveClass('custom-class');
    });

    it('should have role="button" when coordinates are valid', () => {
      render(<CopyableCoordinates latitude={37.7749} longitude={-122.4194} />);
      expect(screen.getByRole('button')).toBeInTheDocument();
    });

    it('should not have role="button" when coordinates are null', () => {
      render(<CopyableCoordinates latitude={null} longitude={null} />);
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
    });

    it('should have appropriate title for clickable coordinates', () => {
      render(<CopyableCoordinates latitude={37.7749} longitude={-122.4194} />);
      const element = screen.getByRole('button');
      expect(element).toHaveAttribute('title', 'Click to copy coordinates');
    });
  });

  describe('copy functionality', () => {
    it('should copy coordinates on click', async () => {
      render(<CopyableCoordinates latitude={37.7749} longitude={-122.4194} />);
      
      fireEvent.click(screen.getByRole('button'));
      
      expect(copyToClipboard).toHaveBeenCalledWith('37.7749, -122.4194');
    });

    it('should show "Copied!" feedback after successful copy', async () => {
      render(<CopyableCoordinates latitude={37.7749} longitude={-122.4194} />);
      
      fireEvent.click(screen.getByRole('button'));
      
      await waitFor(() => {
        expect(screen.getByText('Copied!')).toBeInTheDocument();
      });
    });

    it('should hide "Copied!" feedback after timeout', async () => {
      
      
      render(<CopyableCoordinates latitude={37.7749} longitude={-122.4194} />);
      
      fireEvent.click(screen.getByRole('button'));
      
      
      await waitFor(() => {
        expect(screen.getByText('Copied!')).toBeInTheDocument();
      });
      
      
      await waitFor(() => {
        expect(screen.queryByText('Copied!')).not.toBeInTheDocument();
      }, { timeout: 2000 });
      
      
      expect(screen.getByText('37.7749, -122.4194')).toBeInTheDocument();
    });

    it('should not copy when coordinates are null', async () => {
      render(<CopyableCoordinates latitude={null} longitude={null} />);
      
      const element = screen.getByText('—');
      fireEvent.click(element);
      
      expect(copyToClipboard).not.toHaveBeenCalled();
    });

    it('should not show "Copied!" when copy fails', async () => {
      (copyToClipboard as ReturnType<typeof vi.fn>).mockResolvedValue(false);
      
      render(<CopyableCoordinates latitude={37.7749} longitude={-122.4194} />);
      
      fireEvent.click(screen.getByRole('button'));
      
      
      await vi.waitFor(() => {
        
        expect(screen.queryByText('Copied!')).not.toBeInTheDocument();
      }, { timeout: 200 });
    });
  });

  describe('keyboard accessibility', () => {
    it('should be focusable when coordinates are valid', () => {
      render(<CopyableCoordinates latitude={37.7749} longitude={-122.4194} />);
      const element = screen.getByRole('button');
      expect(element).toHaveAttribute('tabIndex', '0');
    });

    it('should copy on Enter key press', async () => {
      render(<CopyableCoordinates latitude={37.7749} longitude={-122.4194} />);
      
      const element = screen.getByRole('button');
      fireEvent.keyDown(element, { key: 'Enter' });
      
      expect(copyToClipboard).toHaveBeenCalledWith('37.7749, -122.4194');
    });

    it('should copy on Space key press', async () => {
      render(<CopyableCoordinates latitude={37.7749} longitude={-122.4194} />);
      
      const element = screen.getByRole('button');
      fireEvent.keyDown(element, { key: ' ' });
      
      expect(copyToClipboard).toHaveBeenCalledWith('37.7749, -122.4194');
    });

    it('should have aria-label for screen readers', () => {
      render(<CopyableCoordinates latitude={37.7749} longitude={-122.4194} />);
      const element = screen.getByRole('button');
      expect(element).toHaveAttribute('aria-label', 'Copy coordinates: 37.7749, -122.4194');
    });
  });
});
