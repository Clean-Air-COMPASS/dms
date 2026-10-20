import 'i18next';
import type { englishResources } from './resources';

declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'common';
    resources: typeof englishResources;
    returnNull: false;
  }
}
