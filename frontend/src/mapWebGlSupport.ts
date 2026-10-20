/** Check before constructing MapLibre: a failed v6 context leaves a partial map. */
export function isMapWebGl2Available(): boolean {
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('webgl2');
  if (!context) return false;
  context.getExtension('WEBGL_lose_context')?.loseContext();
  return true;
}
