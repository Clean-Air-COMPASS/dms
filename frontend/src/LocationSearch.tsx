import i18n from './i18n';
import * as React from 'react';
import { API_BASE } from './api';

interface LocationSearchProps {
  onLocationSelect: (lat: number, lng: number, zoom: number, displayName: string) => void;
}

type SearchState = 'idle' | 'loading' | 'success' | 'error';


interface GeoapifyResult {
  place_id: string;
  name: string;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  lat: number;
  lon: number;
  result_type: string;
  formatted: string;
}

interface AutocompleteResponse {
  results: GeoapifyResult[];
  cached: boolean;
}


function formatResult(result: GeoapifyResult): { primary: string; secondary: string } {
  const primary = result.name || i18n.t('map:locationSearch.states.unknownLocation');
  
  
  const parts: string[] = [];
  if (result.city && result.city !== primary) parts.push(result.city);
  if (result.state) parts.push(result.state);
  if (result.country) parts.push(result.country);
  
  return {
    primary,
    secondary: parts.length > 0 ? parts.join(', ') : '',
  };
}


function getZoomForResult(result: GeoapifyResult): number {
  const type = result.result_type?.toLowerCase() || '';
  
  
  if (type === 'country') return 5;
  
  
  if (type === 'state' || type === 'region') return 7;
  
  
  if (type === 'county') return 9;
  
  
  if (type === 'city' || type === 'locality' || type === 'town' || type === 'village') return 12;
  
  
  if (type === 'district' || type === 'suburb' || type === 'neighbourhood' || type === 'postcode') return 14;
  
  
  if (type === 'street') return 16;
  
  
  if (type === 'housenumber' || type === 'building' || type === 'amenity') return 17;
  
  
  return 15;
}

const DEBOUNCE_MS = 250;
const MIN_QUERY_LENGTH = 2;
const SEARCH_TIMEOUT_MS = 12000;

const LocationSearch: React.FC<LocationSearchProps> = ({ onLocationSelect }) => {
  const [query, setQuery] = React.useState('');
  const [state, setState] = React.useState<SearchState>('idle');
  const [suggestions, setSuggestions] = React.useState<GeoapifyResult[]>([]);
  const [showSuggestions, setShowSuggestions] = React.useState(false);
  const [selectedIndex, setSelectedIndex] = React.useState(-1);
  const [errorMessage, setErrorMessage] = React.useState<string | null>(null);
  
  const statusId = React.useId();
  const listId = React.useId();
  const requestIdRef = React.useRef(0);
  const requestTimeoutRef = React.useRef<number | null>(null);

  const inputRef = React.useRef<HTMLInputElement>(null);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const debounceRef = React.useRef<number | null>(null);
  const abortControllerRef = React.useRef<AbortController | null>(null);
  const successTimeoutRef = React.useRef<number | null>(null);


  // Invalidate ownership before aborting: a response body may already be resolving.
  const cancelSearch = React.useCallback(() => {
    requestIdRef.current += 1;
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    if (requestTimeoutRef.current) window.clearTimeout(requestTimeoutRef.current);
    if (successTimeoutRef.current) window.clearTimeout(successTimeoutRef.current);
    abortControllerRef.current?.abort();
  }, []);

  
  React.useEffect(() => cancelSearch, [cancelSearch]);

  React.useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
        setSelectedIndex(-1);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  
  const fetchSuggestions = React.useCallback(async (searchQuery: string) => {
    
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    
    const trimmed = searchQuery.trim();
    if (trimmed.length < MIN_QUERY_LENGTH) {
      setSuggestions([]);
      setShowSuggestions(false);
      setState('idle');
      return;
    }

    setState('loading');
    setErrorMessage(null);
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const isCurrent = () => requestId === requestIdRef.current;
    const timeout = window.setTimeout(() => {
      if (!isCurrent()) return;
      requestIdRef.current += 1;
      controller.abort();
      setState('error');
      setErrorMessage(i18n.t('map:locationSearch.messages.searchTimedOut'));
      setSuggestions([]);
      setShowSuggestions(false);
    }, SEARCH_TIMEOUT_MS);
    requestTimeoutRef.current = timeout;

    try {
      
      const base = typeof window !== 'undefined' ? window.location.origin : 'http://localhost';
      const url = new URL(`${API_BASE}/geocode/autocomplete`, base);
      url.searchParams.set('text', trimmed);
      url.searchParams.set('limit', '6');
      
      const response = await fetch(url.toString(), {
        signal: controller.signal,
        headers: { 'Accept': 'application/json' },
      });

      if (!isCurrent()) return;
      if (response.status === 503) {
        
        setState('error');
        setErrorMessage(i18n.t('map:locationSearch.messages.notConfigured'));
        setSuggestions([]);
        setShowSuggestions(false);
        return;
      }

      if (response.status === 429) {
        setState('error');
        setErrorMessage(i18n.t('map:locationSearch.messages.tooManyRequestsTryAgainShortly'));
        setSuggestions([]);
        setShowSuggestions(false);
        return;
      }

      if (!response.ok) {
        throw new Error('search_service_unavailable');
      }

      const data: AutocompleteResponse = await response.json();
      if (!isCurrent()) return;
      if (!Array.isArray(data.results)) throw new Error('invalid_search_response');
      
      setSuggestions(data.results);
      setShowSuggestions((data.results).length > 0);
      setSelectedIndex(-1);
      setState('idle');

      if ((data.results).length === 0 && trimmed.length >= MIN_QUERY_LENGTH) {
        setErrorMessage(i18n.t('map:locationSearch.messages.noMatchesFound'));
      }

    } catch (err) {
      if (!isCurrent()) return;
      if ((err as Error).name === 'AbortError') {
        
        return;
      }
      console.error('Geocoding error:', err);
      setState('error');
      setErrorMessage(i18n.t('map:locationSearch.messages.searchFailed'));
      setSuggestions([]);
      setShowSuggestions(false);
    } finally {
      window.clearTimeout(timeout);
    }
  }, []);

  
  const handleInputChange = React.useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    cancelSearch();
    setState('idle');
    setSuggestions([]);
    setShowSuggestions(false);
    setSelectedIndex(-1);
    const value = e.target.value;
    setQuery(value);
    setErrorMessage(null);
    
    
    if (debounceRef.current) {
      window.clearTimeout(debounceRef.current);
    }

    
    debounceRef.current = window.setTimeout(() => {
      fetchSuggestions(value);
    }, DEBOUNCE_MS);
  }, [fetchSuggestions, cancelSearch]);

  
  const selectSuggestion = React.useCallback((result: GeoapifyResult) => {
    cancelSearch();
    const zoom = getZoomForResult(result);
    const { primary, secondary } = formatResult(result);
    const displayName = secondary ? `${primary}, ${secondary}` : primary;

    
    setQuery(primary);
    setSuggestions([]);
    setShowSuggestions(false);
    setSelectedIndex(-1);
    setState('success');

    
    onLocationSelect(result.lat, result.lon, zoom, displayName);

    
    if (successTimeoutRef.current) {
      window.clearTimeout(successTimeoutRef.current);
    }
    successTimeoutRef.current = window.setTimeout(() => {
      setState('idle');
    }, 1500);
  }, [onLocationSelect, cancelSearch]);

  
  const handleKeyDown = React.useCallback((e: React.KeyboardEvent) => {
    if (!showSuggestions || suggestions.length === 0) {
      if (e.key === 'Escape') {
        cancelSearch();
        setQuery('');
        setState('idle');
        setErrorMessage(null);
        setSuggestions([]);
        setShowSuggestions(false);
        inputRef.current?.blur();
      }
      return;
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex((prev) => Math.min(prev + 1, suggestions.length - 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex((prev) => Math.max(prev - 1, -1));
        break;
      case 'Enter':
        e.preventDefault();
        if (selectedIndex >= 0 && selectedIndex < suggestions.length) {
          selectSuggestion(suggestions[selectedIndex]);
        } else if (suggestions.length > 0) {
          
          selectSuggestion(suggestions[0]);
        }
        break;
      case 'Escape':
        cancelSearch();
        setState('idle');
        e.preventDefault();
        setShowSuggestions(false);
        setSelectedIndex(-1);
        inputRef.current?.blur();
        break;
      case 'Tab':
        setShowSuggestions(false);
        setSelectedIndex(-1);
        break;
    }
  }, [showSuggestions, suggestions, selectedIndex, selectSuggestion, cancelSearch]);

  const handleClear = React.useCallback(() => {
    cancelSearch();
    setQuery('');
    setState('idle');
    setErrorMessage(null);
    setSuggestions([]);
    setShowSuggestions(false);
    setSelectedIndex(-1);
    inputRef.current?.focus();
  }, [cancelSearch]);

  const handleFocus = React.useCallback(() => {
    
    if (suggestions.length > 0) {
      setShowSuggestions(true);
    }
  }, [suggestions.length]);

  return (
    <div className="location-search" ref={containerRef}>
      <div className={`location-search-input-wrapper ${state}`}>
        
        <span className={`location-search-icon ${state}`}>
          {state === 'loading' && (
            <svg className="location-search-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
              <path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round" />
            </svg>
          )}
          {state === 'success' && (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          )}
          {(state === 'idle' || state === 'error') && (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          )}
        </span>

        <input
          ref={inputRef}
          type="text"
          className="location-search-input"
          placeholder={i18n.t('map:locationSearch.placeholders.searchLocation')}
          value={query}
          title={query || undefined}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onFocus={handleFocus}
          aria-label={i18n.t('map:locationSearch.accessibility.searchLocation')}
          role="combobox"
          aria-describedby={statusId}
          aria-controls={listId}
          aria-activedescendant={selectedIndex >= 0 ? `${listId}-${selectedIndex}` : undefined}
          aria-expanded={showSuggestions}
          aria-haspopup="listbox"
          aria-autocomplete="list"
          autoComplete="off"
          spellCheck="false"
        />

        
        {query && (
          <button
            type="button"
            className="location-search-clear"
            onClick={handleClear}
            aria-label={i18n.t('map:locationSearch.accessibility.clearSearch')}
          >
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        )}
      </div>

      
      {showSuggestions && suggestions.length > 0 && (
        <ul id={listId} aria-label={i18n.t('map:locationSearch.accessibility.searchLocation')} className="location-search-suggestions" role="listbox">
          {suggestions.map((result, index) => {
            const { primary, secondary } = formatResult(result);
            const isSelected = index === selectedIndex;
            return (
              <li
                key={result.place_id || `${result.lat}-${result.lon}-${index}`}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={isSelected}
                className={`location-search-suggestion ${isSelected ? 'selected' : ''}`}
                onMouseEnter={() => setSelectedIndex(index)}
                onMouseDown={(e) => {
                  e.preventDefault(); 
                  selectSuggestion(result);
                }}
              >
                <span className="suggestion-icon">
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
                    <circle cx="12" cy="10" r="3" />
                  </svg>
                </span>
                <div className="suggestion-text">
                  <span className="suggestion-primary">{primary}</span>
                  {secondary && <span className="suggestion-secondary">{secondary}</span>}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      
      <div id={statusId} role="status" aria-live="polite"
        className={errorMessage && !showSuggestions ? 'location-search-error' : 'sr-only'}>
        {state === 'loading' ? i18n.t('map:locationSearch.messages.searching') : errorMessage}
      </div>
    </div>
  );
};

export default LocationSearch;
