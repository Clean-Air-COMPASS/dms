# CompassAQ

CompassAQ helps air-quality analysts collect, manage, and explore measurements through data sources, devices, quality checks, maps, and charts.

## Before you begin

Install these on the computer that will run CompassAQ:

- Git.
- Docker Desktop on Windows (using Linux containers), or Docker Engine with the Docker Compose plugin on Linux.

Open PowerShell on Windows or a terminal on Linux and check:

```sh
git --version
docker info
docker compose version
```

You need internet access for downloads and an available port **80**. Use your organization's access controls and HTTPS before making a shared installation publicly accessible.

## Install CompassAQ

**You do not need to create or edit a `.env` file.** CompassAQ supplies initial database configuration, initializes the database, applies migrations, and generates persistent application secrets automatically.

### 1. Download

```sh
git clone https://github.com/phrxst/CompassAQ.git
cd CompassAQ
```

Run all remaining terminal commands from this `CompassAQ` directory.

### 2. Start

On Windows or Linux:

```sh
docker compose up -d --build
```

The first build can take several minutes. Wait for it to finish successfully. No host Python or preparatory build command is required.

### 3. Open

Open [http://localhost/](http://localhost/) in your browser. A starting screen may appear briefly.

For another computer, replace `localhost` with its reachable hostname or IP address, for example `http://192.168.1.50/`. The host firewall and any cloud security group must allow your browser to reach TCP port 80. Do not expose PostgreSQL or Adminer publicly.

### 4. Complete setup

These are the English wizard labels; choose your language on the welcome screen.

1. Select **Continue**, then **Create Admin Account** with your email and a password meeting the displayed requirements. Save your login details.
2. On **Protect your administrator account**, create a passkey if supported, or select **Set up later**.
3. On **Configure Data Source**, leave external providers disabled and keys blank for a simple first installation. **Demo Data** is enabled by default on fresh installs. It generates labeled synthetic observations after setup without provider requests. Uncheck **Enable Demo Data** to opt out. Select **Save Sources & Continue**.
4. On **Configure Location Search**, save an optional Geoapify key or select **Skip for Now**. Without it, location search is unavailable; the Map still opens.
5. Select **Complete Setup & Start Using Platform**. Confirm the home page loads, open **Map**, and sign in with your administrator account when needed.

No external credentials are required. Optional integrations can be configured later in **Admin**:

- **OpenAQ** imports air-quality monitoring data.
- **PurpleAir** imports sensor data; requests can consume credits.
- **AirGradient** imports public reference locations and, optionally, your account's locations.
- **Geoapify** enables map location search.
- **Email/SMTP** sends notifications; configure it under **Email & notifications** after setup.

Leave these integrations disabled or unconfigured during installation testing to avoid provider requests. To stop future samples, open **Admin → Data Sources → Demo Data**, clear **Enable Demo Data**, and save. Existing Demo history is kept.

### 5. Check

```sh
docker compose ps
```

Expect `db`, `api`, `frontend`, and `scheduler` to be running. After startup, `db`, `api`, and `frontend` should show **healthy**. The scheduler has no health-check label. Optional Adminer does not start by default.

For services that exit or stay unhealthy:

```sh
docker compose logs --tail=100
```

Administrators can view the installed application version (for example, **CompassAQ v0.1.0**) and optional build SHA under **Admin → System Preferences → Build Information**.

## Stop, restart, or update

Stop while keeping data and settings:

```sh
docker compose stop
```

Start the existing installation:

```sh
docker compose start
```

Check `docker compose ps` and reopen the application. Setup should remain complete and your account and data should remain available.

To update an unmodified checkout, back up the database and runtime secrets first, then download the latest code:

```sh
git pull --ff-only
```

Repeat `docker compose up -d --build`. Stop/start alone does not install code changes.

Keep the `pg_data` and `compassaq_runtime` Docker volumes. Deleting them removes the database or keys needed to read saved secrets. Deleting persistent data is a separate destructive action, never routine troubleshooting.

## Troubleshooting

- **Docker unavailable:** run `docker info`. Start Docker Desktop, or ask your Linux administrator to check the Docker service and your permissions.
- **Port in use:** check `docker ps` and other host web services for port 80 usage. Ask the owner before stopping anything.
- **Container name conflict:** check `docker ps -a`. Fixed names `aq_db`, `aq_api`, `aq_scheduler`, `aq_frontend`, and optional `aq_adminer` prevent two default installations sharing a host, even with different Compose project names. Use a separate computer for an independent default installation; preserve existing containers and volumes.
- **Wizard missing:** an existing database remembers completed setup. Sign in with the existing account. If expecting a fresh installation, check the host and checkout. Do not delete the database to force setup.
- **Unreachable or stuck starting:** check status and logs above. Try `http://localhost/` on the host. If only remote access fails, check the hostname/IP, firewall, and cloud security group for port 80. Remove credentials from logs before requesting help.

## Contributing

Contribution guidelines are still being defined. External contributions should not be submitted or assumed accepted until the project maintainers define the contribution process.

## License

CompassAQ is licensed under [Apache 2.0](https://github.com/Clean-Air-COMPASS/dms/blob/main/LICENSE)
