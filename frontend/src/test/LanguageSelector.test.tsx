import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import LanguageSelector from '../components/LanguageSelector';

describe('LanguageSelector', () => {
  it('offers English and Spanish as production-enabled languages', () => {
    render(<LanguageSelector value="en" onChange={vi.fn()} />);

    expect(screen.getByRole('option', { name: 'English' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Español' })).toBeInTheDocument();
  });

  it('supports the nullable user-override presentation', () => {
    const onSelectSystemDefault = vi.fn();
    render(
      <LanguageSelector
        value="en"
        onChange={vi.fn()}
        includeSystemDefault
        systemDefaultSelected
        onSelectSystemDefault={onSelectSystemDefault}
      />,
    );

    const selector = screen.getByRole('combobox', { name: 'Language' });
    expect(selector).toHaveValue('system');
    fireEvent.change(selector, { target: { value: 'system' } });
    expect(onSelectSystemDefault).toHaveBeenCalledOnce();
  });

  it('remains visible in production layouts when Spanish is enabled', () => {
    render(<LanguageSelector value="en" onChange={vi.fn()} hideWhenSingleLanguage />);
    expect(screen.getByRole('combobox', { name: 'Language' })).toBeInTheDocument();
  });

  it('reports a Spanish selection', () => {
    const onChange = vi.fn();
    render(<LanguageSelector value="en" onChange={onChange} />);
    fireEvent.change(screen.getByRole('combobox', { name: 'Language' }), { target: { value: 'es' } });
    expect(onChange).toHaveBeenCalledWith('es');
  });
});
