import { beforeEach, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AdminSourceDetail from '../AdminSourceDetail';
import i18n from '../i18n';

const mocks = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn() }));
vi.mock('../api', () => ({ listExternalAPIs: mocks.list }));
vi.mock('../auth', () => ({ authFetchJson: mocks.detail }));
vi.mock('../components/UserMenu', () => ({ default: () => null }));
vi.mock('../AdminSourceForm', () => ({ default: () => null }));
vi.mock('../TestImportTab', () => ({ default: () => <section id="source-run-now">Run import now</section> }));
vi.mock('../SchedulesTab', () => ({ default: () => <section id="source-schedule">Automatic imports</section> }));

beforeEach(() => vi.resetAllMocks());
function renderDetail() {
  return render(<MemoryRouter initialEntries={['/admin/sources/1']}><Routes>
    <Route path="/admin/sources/:id" element={<AdminSourceDetail />} />
  </Routes></MemoryRouter>);
}

it.each(['en', 'es'])('uses the loaded source name in the heading and breadcrumb in %s', async language => {
  await i18n.changeLanguage(language);
  const source = { external_api_id: 1, name: 'OpenAQ regional monitoring network with a long source name', enabled: true };
  mocks.list.mockResolvedValue([source]);
  let resolve!: (value: unknown) => void;
  mocks.detail.mockReturnValue(new Promise(done => { resolve = done; }));
  const view = renderDetail();
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(i18n.t('dataSources:adminSourceDetail.tooltips.dataSource'));
  await act(async () => { await Promise.resolve(); });
  await act(async () => resolve(source));
  expect(await screen.findByRole('heading', { level: 1, name: source.name })).toBeInTheDocument();
  expect(view.container.querySelector('.breadcrumbs')).toHaveTextContent(source.name);
  expect(screen.queryByText('Source 1')).not.toBeInTheDocument();
});

it('does not substitute another source when the requested source cannot load', async () => {
  await i18n.changeLanguage('en');
  mocks.list.mockResolvedValue([{ external_api_id: 2, name: 'Different provider' }]);
  mocks.detail.mockRejectedValue(new Error('Fixture failure'));
  renderDetail();
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  expect(screen.queryByText('Different provider')).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Data Source');
});

it('orders readiness, configuration, run now, scheduling and monitoring in the document', async () => {
  await i18n.changeLanguage('en');
  const source = { external_api_id: 1, name: 'OpenAQ', enabled: true, has_api_key: false, is_configured: false, is_runnable: false };
  mocks.list.mockResolvedValue([source]);
  mocks.detail.mockResolvedValue(source);
  const view = renderDetail();
  await screen.findByRole('heading', { name: 'Needs configuration' });
  const sections = ['.source-readiness', '#source-configuration', '#source-run-now', '#source-schedule', '#source-monitoring'].map(selector => view.container.querySelector(selector)!);
  for (let index = 1; index < sections.length; index++) {
    expect(sections[index - 1].compareDocumentPosition(sections[index]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  }
  expect(screen.getByRole('link', { name: 'View Devices' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Last import' })).toBeInTheDocument();
});
