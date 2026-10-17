import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { I18nProvider } from '../i18n/I18nContext';

const { analyticsConsent, setAnalyticsConsent } = vi.hoisted(() => ({
  analyticsConsent: vi.fn(), setAnalyticsConsent: vi.fn(),
}));
vi.mock('../lib/analytics', () => ({
  analyticsConsent, setAnalyticsConsent, optionalAnalyticsConfigured: () => true,
}));
import { PrivacyControls } from './PrivacyControls';

beforeEach(() => {
  analyticsConsent.mockReset().mockReturnValue(false);
  setAnalyticsConsent.mockReset();
});

function remoteChoice(allowed: boolean) {
  analyticsConsent.mockReturnValue(allowed);
  // The unchanged analytics module emits no detail for cross-tab storage events.
  act(() => window.dispatchEvent(new CustomEvent('stx-analytics-choice')));
}

it('removes a stale acceptance/reload notice after cross-tab revocation', () => {
  render(<I18nProvider initialLocale="en"><PrivacyControls /></I18nProvider>);
  setAnalyticsConsent.mockReturnValue({ allowed: true, saved: true, nextVisit: true });
  fireEvent.click(screen.getByRole('button', { name: 'Allow optional analytics' }));
  expect(screen.getByRole('button', { name: 'Reload page' })).toBeVisible();
  remoteChoice(false);
  expect(screen.getByRole('button', { name: 'Decline optional analytics' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.queryByRole('button', { name: 'Reload page' })).not.toBeInTheDocument();
});

it('replaces an unsaved-choice error with the current saved cross-tab result', () => {
  render(<I18nProvider initialLocale="en"><PrivacyControls /></I18nProvider>);
  setAnalyticsConsent.mockReturnValue({ allowed: false, saved: false, nextVisit: false });
  fireEvent.click(screen.getByRole('button', { name: 'Decline optional analytics' }));
  expect(screen.getByRole('alert')).toHaveTextContent('could not save your choice');
  remoteChoice(true);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Allow optional analytics' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.queryByRole('button', { name: 'Reload page' })).not.toBeInTheDocument();
});
