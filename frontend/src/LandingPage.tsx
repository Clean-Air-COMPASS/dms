import { Link } from 'react-router-dom';
import cleanAirFundLogo from './assets/logos/clean-air-fund-logo.svg';
import nrdcLogo from './assets/logos/nrdc-logo.png';
import openAqLogo from './assets/logos/openaq-logo.svg';
import sonomaTechnologyLogo from './assets/logos/sonoma-technology-logo.svg';
import './LandingPage.css';


function LandingPage() {
  return (
    <div className="landing-page">
      
      <header className="landing-header">
        <div className="landing-container">
          <div className="landing-nav">
              <div className="landing-logo">
              <span className="logo-text">AQ Data Platform</span>
              <a
                href="https://cleanaircompass.org"
                target="_blank"
                rel="noopener noreferrer"
                className="logo-badge"
              >
                by Clean Air COMPASS
              </a>
            </div>
            <nav className="landing-nav-links">
              <a
                href="https://cleanaircompass.org/about"
                target="_blank"
                rel="noopener noreferrer"
              >
                About COMPASS
              </a>
              <Link to="/map" className="nav-cta">
                Open Map
              </Link>
            </nav>
          </div>
        </div>
      </header>

      
      <section className="hero-section">
        <div className="landing-container">
          <div className="hero-content">
            <h1 className="hero-title">
              Open-Source Air Quality
              <br />
              Data Management
            </h1>
            <p className="hero-subtitle">
              A collaborative, community-informed platform for collecting,
              managing, and visualizing air quality measurement data—empowering
              communities, researchers, and organizations worldwide.
            </p>
            <div className="hero-actions">
              <Link to="/map" className="btn-primary">
                Explore the Map
              </Link>
              <a
                href="https://cleanaircompass.org/participate"
                target="_blank"
                rel="noopener noreferrer"
                className="btn-secondary"
              >
                Get Involved
              </a>
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
                of the world breathes unhealthy air
              </span>
            </div>
            <div className="stat-item">
              <span className="stat-number">1 in 8</span>
              <span className="stat-label">
                premature deaths globally linked to air pollution
              </span>
            </div>
            <div className="stat-item">
              <span className="stat-number">Open</span>
              <span className="stat-label">
                source platform for global collaboration
              </span>
            </div>
          </div>
        </div>
      </section>

      
      <section className="features-section">
        <div className="landing-container">
          <h2 className="section-title">Why This Platform Matters</h2>
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
              <h3 className="feature-title">Air Quality Data</h3>
              <p className="feature-description">
                Aggregate measurements from multiple sources—OpenAQ, PurpleAir,
                and more—into a unified, quality-controlled data repository.
                Real-time and historical data at your fingertips.
              </p>
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
              <h3 className="feature-title">Open Source</h3>
              <p className="feature-description">
                A customizable, open-source data management system that fosters
                collaboration, reduces redundancy, and enhances accessibility
                for global air quality efforts.
              </p>
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
              <h3 className="feature-title">Community-Informed</h3>
              <p className="feature-description">
                Built with input from a global community of practice. Shared
                learning accelerates progress, helping overcome data management
                hurdles for more effective use of air quality information.
              </p>
            </article>
          </div>
        </div>
      </section>

      
      <section className="about-section">
        <div className="landing-container">
          <div className="about-grid">
            <div className="about-content">
              <h2 className="section-title">About Clean Air COMPASS</h2>
              <p>
                The Clean Air COMPASS project emerged from a critical global
                need: effective air quality data management. Existing systems
                are falling short as monitoring efforts by governments,
                community-based organizations, and other institutions increase.
              </p>
              <p>
                Proprietary or custom-built solutions can be costly, opaque,
                and inefficient. This initiative directly addresses these pain
                points by offering a customizable open-source Data Management
                System (DMS), born from global feedback to meet expressed needs.
              </p>
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
                      Led By
                    </span>
                    <span className="rounded-full bg-[#e8f1fb] px-3 py-1 text-[11px] font-medium text-[#1f2d3d]">
                      Mission partners &amp; seed funding
                    </span>
                  </div>
                  <p className="text-sm text-[#1f2937]">
                    Natural Resources Defense Council (NRDC), OpenAQ, and Sonoma
                    Technology, Inc., with seed funding from the Clean Air Fund.
                  </p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 md:gap-4">
                    <a
                      href="https://www.nrdc.org/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group flex items-center justify-center rounded-lg border border-[#e6edf7] bg-white/80 p-3 transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_10px_25px_rgba(6,71,137,0.08)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0b5fff] focus-visible:ring-offset-2 focus-visible:ring-offset-white"
                    >
                      <img
                        src={nrdcLogo}
                        alt="Natural Resources Defense Council"
                        className="h-16 w-auto max-w-[170px] object-contain"
                      />
                    </a>
                    <a
                      href="https://openaq.org/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group flex items-center justify-center rounded-lg border border-[#e6edf7] bg-white/80 p-3 transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_10px_25px_rgba(6,71,137,0.08)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0b5fff] focus-visible:ring-offset-2 focus-visible:ring-offset-white"
                      >
                      <img
                        src={openAqLogo}
                        alt="OpenAQ"
                        className="h-14 w-auto max-w-[160px] object-contain"
                      />
                    </a>
                    <a
                      href="https://www.sonomatech.com/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group flex items-center justify-center rounded-lg border border-[#e6edf7] bg-white/80 p-3 transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_10px_25px_rgba(6,71,137,0.08)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0b5fff] focus-visible:ring-offset-2 focus-visible:ring-offset-white"
                      >
                      <img
                        src={sonomaTechnologyLogo}
                        alt="Sonoma Technology"
                        className="h-14 w-auto max-w-[170px] object-contain"
                      />
                    </a>
                    <a
                      href="https://www.cleanairfund.org/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group flex items-center justify-center rounded-lg border border-[#e6edf7] bg-white/80 p-3 transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_10px_25px_rgba(6,71,137,0.08)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0b5fff] focus-visible:ring-offset-2 focus-visible:ring-offset-white"
                    >
                      <img
                        src={cleanAirFundLogo}
                        alt="Clean Air Fund"
                        className="h-12 w-auto max-w-[150px] object-contain"
                      />
                    </a>
                  </div>
                </div>
              </section>
            </div>
            <div className="about-cta">
              <div className="cta-card">
                <h3>Ready to Explore?</h3>
                <p>
                  View real-time air quality data from monitoring devices
                  around the world on our interactive map.
                </p>
                <Link to="/map" className="btn-primary btn-large">
                  Launch the Map
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      
      <section className="benefits-section">
        <div className="landing-container">
          <h2 className="section-title">Who Benefits</h2>
          <div className="benefits-grid">
            <div className="benefit-item">
              <h4>Communities</h4>
              <p>
                Access transparent, quality-controlled air quality data to
                understand local pollution levels and advocate for cleaner air.
              </p>
            </div>
            <div className="benefit-item">
              <h4>Researchers</h4>
              <p>
                Leverage standardized, multi-source data for studies, with
                built-in QA/QC and flexible aggregation periods.
              </p>
            </div>
            <div className="benefit-item">
              <h4>Organizations</h4>
              <p>
                Deploy an open-source DMS without vendor lock-in, customizable
                to your monitoring network and reporting needs.
              </p>
            </div>
            <div className="benefit-item">
              <h4>Governments</h4>
              <p>
                Integrate regulatory and low-cost sensor data into a unified
                platform for policy decisions and public health alerts.
              </p>
            </div>
          </div>
        </div>
      </section>

      
      <footer className="landing-footer">
        <div className="landing-container">
          <div className="footer-content">
            <div className="footer-brand">
              <span className="footer-logo">AQ Data Platform</span>
              <p className="footer-tagline">
                Part of the Clean Air COMPASS initiative
              </p>
            </div>
            <div className="footer-links">
              <a
                href="https://cleanaircompass.org"
                target="_blank"
                rel="noopener noreferrer"
              >
                Clean Air COMPASS
              </a>
              <a
                href="https://cleanaircompass.org/about"
                target="_blank"
                rel="noopener noreferrer"
              >
                About
              </a>
              <a
                href="https://cleanaircompass.org/participate"
                target="_blank"
                rel="noopener noreferrer"
              >
                Participate
              </a>
              <a
                href="https://github.com/clean-air-compass"
                target="_blank"
                rel="noopener noreferrer"
              >
                GitHub
              </a>
            </div>
          </div>
          <div className="footer-bottom">
            <p>© {new Date().getFullYear()} Clean Air COMPASS</p>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default LandingPage;
