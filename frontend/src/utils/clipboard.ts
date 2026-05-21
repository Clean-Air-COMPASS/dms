


export async function copyToClipboard(text: string): Promise<boolean> {
  if (!text) return false;
  
  try {
    
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      await navigator.clipboard.writeText(text);
      return true;
    }
    
    
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-9999px';
    textArea.style.top = '-9999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    
    try {
      const success = document.execCommand('copy');
      document.body.removeChild(textArea);
      return success;
    } catch {
      document.body.removeChild(textArea);
      return false;
    }
  } catch {
    return false;
  }
}


export function formatCoordinates(
  lat: number | null | undefined,
  lon: number | null | undefined,
  precision: number = 4
): string {
  if (lat == null || lon == null) return '—';
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return '—';
  return `${lat.toFixed(precision)}, ${lon.toFixed(precision)}`;
}
