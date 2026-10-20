import admin from './locales/en/admin.json';
import analytics from './locales/en/analytics.json';
import aq from './locales/en/aq.json';
import auth from './locales/en/auth.json';
import common from './locales/en/common.json';
import dataSources from './locales/en/dataSources.json';
import devices from './locales/en/devices.json';
import events from './locales/en/events.json';
import landing from './locales/en/landing.json';
import map from './locales/en/map.json';
import qualityControl from './locales/en/qualityControl.json';
import emailNotifications from './locales/en/emailNotifications.json';
import setup from './locales/en/setup.json';
import users from './locales/en/users.json';
import adminEs from './locales/es/admin.json';
import analyticsEs from './locales/es/analytics.json';
import aqEs from './locales/es/aq.json';
import authEs from './locales/es/auth.json';
import commonEs from './locales/es/common.json';
import dataSourcesEs from './locales/es/dataSources.json';
import devicesEs from './locales/es/devices.json';
import eventsEs from './locales/es/events.json';
import landingEs from './locales/es/landing.json';
import mapEs from './locales/es/map.json';
import qualityControlEs from './locales/es/qualityControl.json';
import emailNotificationsEs from './locales/es/emailNotifications.json';
import setupEs from './locales/es/setup.json';
import usersEs from './locales/es/users.json';

export const namespaces = [
  'common',
  'landing',
  'map',
  'analytics',
  'admin',
  'devices',
  'dataSources',
  'qualityControl',
  'emailNotifications',
  'events',
  'users',
  'auth',
  'setup',
  'aq',
] as const;

export const englishResources = {
  common,
  landing,
  map,
  analytics,
  admin,
  devices,
  dataSources,
  qualityControl,
  emailNotifications,
  events,
  users,
  auth,
  setup,
  aq,
} as const;

export const spanishResources = {
  common: commonEs,
  landing: landingEs,
  map: mapEs,
  analytics: analyticsEs,
  admin: adminEs,
  devices: devicesEs,
  dataSources: dataSourcesEs,
  qualityControl: qualityControlEs,
  emailNotifications: emailNotificationsEs,
  events: eventsEs,
  users: usersEs,
  auth: authEs,
  setup: setupEs,
  aq: aqEs,
} as const;

export const resources = {
  en: englishResources,
  es: spanishResources,
} as const;
