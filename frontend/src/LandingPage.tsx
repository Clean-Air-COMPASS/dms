import { Trans, useTranslation } from 'react-i18next';
import i18n from './i18n';
import { Link } from 'react-router-dom';
import cleanAirFundLogo from './assets/logos/clean-air-fund-logo.svg';
import nrdcLogo from './assets/logos/nrdc-logo.webp';
import openAqLogo from './assets/logos/openaq-logo.svg';
import spherosEnvironmentalLogo from './assets/logos/spheros-environmental-logo.webp';
import './LandingPage.css';
import LanguageSelector from './components/LanguageSelector';
import {
  FALLBACK_LANGUAGE_CODE,
  writeAnonymousLanguagePreference,
  type SupportedLanguageCode,
} from './i18n/languagePreferences';


function LandingPage() {
  useTranslation();

  function selectAnonymousLanguage(languageCode: SupportedLanguageCode): void {
    writeAnonymousLanguagePreference(window.localStorage, languageCode);
    void i18n.changeLanguage(languageCode);
  }

  return (
    <div className="landing-page">
      
      <header className="landing-header">
        <div className="landing-container">
          <div className="landing-nav">
              <div className="landing-logo">
              <span className="logo-text"><Trans ns="landing" i18nKey="landingPage.text.aqDataPlatform" /></span>
              <a
                href="https://cleanaircompass.org"
                target="_blank"
                rel="noopener noreferrer"
                className="logo-badge"
              >
                <Trans ns="landing" i18nKey="landingPage.actions.cleanAirCompass" /></a>
            </div>
            <nav className="landing-nav-links">
              <LanguageSelector
                id="landing-language-selector"
                value={(i18n.resolvedLanguage as SupportedLanguageCode) ?? FALLBACK_LANGUAGE_CODE}
                onChange={selectAnonymousLanguage}
                hideWhenSingleLanguage
              />
              <Link to="/map" className="nav-cta">
                <Trans ns="landing" i18nKey="landingPage.actions.openMap" /></Link>
            </nav>
          </div>
        </div>
      </header>

      
      <section className="hero-section">
        <div className="landing-container">
          <div className="hero-content">
            <h1 className="hero-title">
              <Trans ns="landing" i18nKey="landingPage.headings.openSourceAirQuality" /><br />
              <Trans ns="landing" i18nKey="landingPage.headings.dataManagement" /></h1>
            <p className="hero-subtitle">
              <Trans ns="landing" i18nKey="landingPage.text.collaborativeCommunityInformedPlatformCollectingManaging" /></p>
            <div className="hero-actions">
              <Link to="/map" className="btn-primary">
                <Trans ns="landing" i18nKey="landingPage.actions.exploreMap" /></Link>
              <a
                href="https://cleanaircompass.org/participate"
                target="_blank"
                rel="noopener noreferrer"
                className="btn-secondary"
              >
                <Trans ns="landing" i18nKey="landingPage.actions.getInvolved" /></a>
            </div>
          </div>
        </div>
      </section>

      
      <section className="stats-section">
        <div className="landing-container">
          <div className="stats-grid">
            <div className="stat-item">
              <span className="stat-number">99%</span>
              <span className="stat-label">
                <Trans ns="landing" i18nKey="landingPage.text.worldBreathesUnhealthyAir" /></span>
            </div>
            <div className="stat-item">
              <span className="stat-number"><Trans ns="landing" i18nKey="landingPage.text.18" /></span>
              <span className="stat-label">
                <Trans ns="landing" i18nKey="landingPage.text.prematureDeathsGloballyLinkedAirPollution" /></span>
            </div>
            <div className="stat-item">
              <span className="stat-number"><Trans ns="landing" i18nKey="landingPage.text.open" /></span>
              <span className="stat-label">
                <Trans ns="landing" i18nKey="landingPage.text.sourcePlatformGlobalCollaboration" /></span>
            </div>
          </div>
        </div>
      </section>

      
      <section className="features-section">
        <div className="landing-container">
          <h2 className="section-title"><Trans ns="landing" i18nKey="landingPage.headings.whyPlatformMatters" /></h2>
          <div className="features-grid">
            <article className="feature-card">
              <div className="feature-icon" aria-hidden="true">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                </svg>
              </div>
              <h3 className="feature-title"><Trans ns="landing" i18nKey="landingPage.headings.airQualityData" /></h3>
              <p className="feature-description">
                <Trans ns="landing" i18nKey="landingPage.text.aggregateMeasurementsMultipleSourcesOpenAq" /></p>
            </article>

            <article className="feature-card">
              <div className="feature-icon" aria-hidden="true">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
                  <polyline points="7.5 4.21 12 6.81 16.5 4.21" />
                  <polyline points="7.5 19.79 7.5 14.6 3 12" />
                  <polyline points="21 12 16.5 14.6 16.5 19.79" />
                  <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
                  <line x1="12" y1="22.08" x2="12" y2="12" />
                </svg>
              </div>
              <h3 className="feature-title"><Trans ns="landing" i18nKey="landingPage.headings.openSource" /></h3>
              <p className="feature-description">
                <Trans ns="landing" i18nKey="landingPage.text.customizableOpenSourceDataManagementSystem" /></p>
            </article>

            <article className="feature-card">
              <div className="feature-icon" aria-hidden="true">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                  <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
              </div>
              <h3 className="feature-title"><Trans ns="landing" i18nKey="landingPage.headings.communityInformed" /></h3>
              <p className="feature-description">
                <Trans ns="landing" i18nKey="landingPage.text.builtInputGlobalCommunityPracticeShared" /></p>
            </article>
          </div>
        </div>
      </section>

      
      <section className="about-section">
        <div className="landing-container">
          <div className="about-grid">
            <div className="about-content">
              <h2 className="section-title"><Trans ns="landing" i18nKey="landingPage.headings.aboutCleanAirCompass" /></h2>
              <p>
                <Trans ns="landing" i18nKey="landingPage.text.cleanAirCompassProjectEmergedCritical" /></p>
              <p>
                <Trans ns="landing" i18nKey="landingPage.text.proprietaryCustomBuiltSolutionsCanCostly" /></p>
              <section
                className="landing-led-by mt-8 rounded-xl bg-white/90 p-6 shadow-md ring-1 ring-[#e1e9f5]"
                aria-labelledby="led-by-title"
              >
                
                <div className="flex flex-col gap-4">
                  <div className="flex items-center gap-3">
                    <span
                      id="led-by-title"
                      className="text-xs font-semibold uppercase tracking-[0.14em] text-[#0a4d86]"
                    >
                      <Trans ns="landing" i18nKey="landingPage.text.led" /></span>
                    <span className="rounded-full bg-[#e8f1fb] px-3 py-1 text-[11px] font-medium text-[#1f2d3d]">
                      <Trans ns="landing" i18nKey="landingPage.text.missionPartnersAmpSeedFunding" /></span>
                  </div>
                  <p className="text-sm text-[#1f2937]">
                    <Trans ns="landing" i18nKey="landingPage.text.naturalResourcesDefenseCouncilNrdcOpen" /></p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 md:gap-4">
                    <a
                      href="https://www.nrdc.org/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="partner-logo-card group flex items-center justify-center rounded-lg border border-[#e6edf7] bg-white/80 p-3 transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_10px_25px_rgba(6,71,137,0.08)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0b5fff] focus-visible:ring-offset-2 focus-visible:ring-offset-white"
                    >
                      <img
                        src={nrdcLogo}
                        alt={i18n.t('landing:landingPage.accessibility.naturalResourcesDefenseCouncil')}
                        className="partner-logo partner-logo--nrdc"
                      />
                    </a>
                    <a
                      href="https://openaq.org/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="partner-logo-card group flex items-center justify-center rounded-lg border border-[#e6edf7] bg-white/80 p-3 transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_10px_25px_rgba(6,71,137,0.08)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0b5fff] focus-visible:ring-offset-2 focus-visible:ring-offset-white"
                      >
                      <img
                        src={openAqLogo}
                        alt="OpenAQ"
                        className="partner-logo partner-logo--openaq"
                      />
                    </a>
                    <a
                      href="https://spherosenv.com/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="partner-logo-card group flex items-center justify-center rounded-lg border border-[#e6edf7] bg-white/80 p-3 transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_10px_25px_rgba(6,71,137,0.08)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0b5fff] focus-visible:ring-offset-2 focus-visible:ring-offset-white"
                      >
                      <img
                        src={spherosEnvironmentalLogo}
                        alt={i18n.t('landing:landingPage.accessibility.spherosEnvironmental')}
                        className="partner-logo partner-logo--spheros"
                      />
                    </a>
                    <a
                      href="https://www.cleanairfund.org/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="partner-logo-card group flex items-center justify-center rounded-lg border border-[#e6edf7] bg-white/80 p-3 transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_10px_25px_rgba(6,71,137,0.08)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0b5fff] focus-visible:ring-offset-2 focus-visible:ring-offset-white"
                    >
                      <img
                        src={cleanAirFundLogo}
                        alt={i18n.t('landing:landingPage.accessibility.cleanAirFund')}
                        className="partner-logo partner-logo--clean-air-fund"
                      />
                    </a>
                  </div>
                </div>
              </section>
            </div>
            <div className="about-cta">
              <div className="cta-card">
                <h3><Trans ns="landing" i18nKey="landingPage.headings.readyExplore" /></h3>
                <p>
                  <Trans ns="landing" i18nKey="landingPage.text.viewRealTimeAirQualityData" /></p>
                <Link to="/map" className="btn-primary btn-large">
                  <Trans ns="landing" i18nKey="landingPage.actions.launchMap" /></Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      
      <section className="benefits-section">
        <div className="landing-container">
          <h2 className="section-title"><Trans ns="landing" i18nKey="landingPage.headings.whoBenefits" /></h2>
          <div className="benefits-grid">
            <div className="benefit-item">
              <h4><Trans ns="landing" i18nKey="landingPage.headings.communities" /></h4>
              <p>
                <Trans ns="landing" i18nKey="landingPage.text.accessTransparentQualityControlledAirQuality" /></p>
            </div>
            <div className="benefit-item">
              <h4><Trans ns="landing" i18nKey="landingPage.headings.researchers" /></h4>
              <p>
                <Trans ns="landing" i18nKey="landingPage.text.leverageStandardizedMultiSourceDataStudies" /></p>
            </div>
            <div className="benefit-item">
              <h4><Trans ns="landing" i18nKey="landingPage.headings.organizations" /></h4>
              <p>
                <Trans ns="landing" i18nKey="landingPage.text.deployOpenSourceDmsWithoutVendor" /></p>
            </div>
            <div className="benefit-item">
              <h4><Trans ns="landing" i18nKey="landingPage.headings.governments" /></h4>
              <p>
                <Trans ns="landing" i18nKey="landingPage.text.integrateRegulatoryLowCostSensorData" /></p>
            </div>
          </div>
        </div>
      </section>

      
      <footer className="landing-footer">
        <div className="landing-container">
          <div className="footer-content">
            <div className="footer-brand">
              <span className="footer-logo"><Trans ns="landing" i18nKey="landingPage.text.aqDataPlatform2" /></span>
              <p className="footer-tagline">
                <Trans ns="landing" i18nKey="landingPage.text.partCleanAirCompassInitiative" /></p>
            </div>
            <div className="footer-links">
              <a
                href="https://cleanaircompass.org"
                target="_blank"
                rel="noopener noreferrer"
              >
                <Trans ns="landing" i18nKey="landingPage.actions.cleanAirCompass2" /></a>
              <a
                href="https://cleanaircompass.org/about"
                target="_blank"
                rel="noopener noreferrer"
              >
                <Trans ns="landing" i18nKey="landingPage.actions.about" /></a>
              <a
                href="https://cleanaircompass.org/participate"
                target="_blank"
                rel="noopener noreferrer"
              >
                <Trans ns="landing" i18nKey="landingPage.actions.participate" /></a>
              <a
                href="https://github.com/clean-air-compass"
                target="_blank"
                rel="noopener noreferrer"
              >
                <Trans ns="landing" i18nKey="landingPage.actions.gitHub" /></a>
            </div>
          </div>
          <div className="footer-bottom">
            <p>© {new Date().getFullYear()} {' '}<Trans ns="landing" i18nKey="landingPage.text.cleanAirCompass" /></p>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default LandingPage;
